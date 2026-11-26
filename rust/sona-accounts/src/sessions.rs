//! Règles des sessions d'écoute (écoute ensemble) : qui peut entrer, qui peut
//! quoi, comment on expulse ou on bannit. État purement en mémoire, sans
//! entrée/sortie : le serveur musique y branche sa file, ses votes et son chat
//! et lui passe, pour chaque appel, les relations venues de `/internal/relations`.
//!
//! Principes (cahier des charges, section 12) :
//!  * une session n'est jamais publique par défaut ;
//!  * accès : amis de l'hôte (défaut), invitation à jeton qui expire, ou
//!    « ouverte avec le lien » (désactivé par défaut) ;
//!  * un utilisateur bloqué (dans un sens ou dans l'autre) ne peut pas
//!    rejoindre et n'est jamais vu dans la liste des participants ;
//!  * verrouillée, fermée, expirée ou pleine : plus de nouveaux participants ;
//!  * à la fermeture, tout ce qui était temporaire est effacé.

use chrono::{DateTime, Duration, Utc};
use rand::RngCore;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashSet};
use uuid::Uuid;

pub const MAX_PARTICIPANTS_LIMIT: usize = 50;
pub const DEFAULT_MAX_PARTICIPANTS: usize = 12;
pub const MAX_INVITE_TTL: Duration = Duration::days(7);
pub const DEFAULT_INVITE_TTL: Duration = Duration::hours(1);
pub const SESSION_LIFETIME: Duration = Duration::hours(12);

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Role {
    Listener,
    Moderator,
    Host,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Access {
    /// Seuls les amis acceptés de l'hôte (par défaut).
    Friends,
    /// Seulement avec un jeton d'invitation valable.
    InviteOnly,
    /// Quiconque a le lien (jamais activé sans geste explicite de l'hôte).
    OpenWithLink,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Who {
    Host,
    Moderators,
    Everyone,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Action {
    AddTracks,
    ChangeTrack,
    Pause,
}

#[derive(Debug, Clone, Copy)]
pub struct Permissions {
    pub add_tracks: Who,
    pub change_track: Who,
    pub pause: Who,
}

impl Default for Permissions {
    fn default() -> Self {
        Permissions { add_tracks: Who::Everyone, change_track: Who::Moderators, pause: Who::Moderators }
    }
}

/// Relation entre la personne qui agit et un autre compte, telle que la renvoie
/// `public.batch_relations` (côté serveur, jamais fournie par le client).
#[derive(Debug, Clone, Copy, Default)]
pub struct Relation {
    pub friend: bool,
    pub blocked: bool,
    /// Compte actif (ni suspendu, ni banni, ni en quarantaine).
    pub visible: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum SessionError {
    /// Message volontairement neutre : ne révèle ni un blocage ni un bannissement.
    #[error("Cette session n'est pas disponible.")]
    Unavailable,
    #[error("La session est verrouillée.")]
    Locked,
    #[error("La session est complète.")]
    Full,
    #[error("Invitation invalide ou expirée.")]
    BadInvite,
    #[error("Action réservée à l'hôte ou aux modérateurs.")]
    NotAllowed,
    #[error("Participant introuvable.")]
    NoSuchMember,
    #[error("Durée d'invitation invalide.")]
    BadTtl,
}

#[derive(Debug, Clone)]
pub struct Member {
    pub role: Role,
    pub joined_at: DateTime<Utc>,
    pub muted: bool,
}

#[derive(Debug, Clone)]
struct Invite {
    id: Uuid,
    token_hash: [u8; 32],
    expires_at: DateTime<Utc>,
    revoked: bool,
}

#[derive(Debug, Clone)]
pub struct Session {
    pub code: String,
    pub access: Access,
    pub locked: bool,
    pub closed: bool,
    pub chat_enabled: bool,
    pub max_participants: usize,
    pub permissions: Permissions,
    pub created_at: DateTime<Utc>,
    members: BTreeMap<Uuid, Member>,
    banned: HashSet<Uuid>,
    invites: Vec<Invite>,
}

fn hash_token(token: &str) -> [u8; 32] {
    Sha256::digest(token.as_bytes()).into()
}

/// 192 bits d'aléa, en hexadécimal.
fn random_token() -> String {
    let mut b = [0u8; 24];
    rand::thread_rng().fill_bytes(&mut b);
    hex::encode(b)
}

impl Session {
    pub fn new(code: impl Into<String>, host: Uuid, now: DateTime<Utc>) -> Self {
        let mut members = BTreeMap::new();
        members.insert(host, Member { role: Role::Host, joined_at: now, muted: false });
        Session {
            code: code.into(),
            access: Access::Friends,
            locked: false,
            closed: false,
            chat_enabled: true,
            max_participants: DEFAULT_MAX_PARTICIPANTS,
            permissions: Permissions::default(),
            created_at: now,
            members,
            banned: HashSet::new(),
            invites: Vec::new(),
        }
    }

    pub fn host(&self) -> Option<Uuid> {
        self.members.iter().find(|(_, m)| m.role == Role::Host).map(|(id, _)| *id)
    }

    pub fn role_of(&self, user: Uuid) -> Option<Role> {
        self.members.get(&user).map(|m| m.role)
    }

    pub fn is_member(&self, user: Uuid) -> bool {
        self.members.contains_key(&user)
    }

    pub fn is_expired(&self, now: DateTime<Utc>) -> bool {
        now >= self.created_at + SESSION_LIFETIME
    }

    pub fn participant_count(&self) -> usize {
        self.members.len()
    }

    /// Les participants que `viewer` a le droit de voir : jamais quelqu'un
    /// qu'il a bloqué ou qui l'a bloqué (`relation` vient de batch_relations).
    pub fn visible_members<F: Fn(Uuid) -> Relation>(&self, viewer: Uuid, relation: F) -> Vec<(Uuid, Role)> {
        self.members
            .iter()
            .filter(|(id, _)| **id == viewer || !relation(**id).blocked)
            .map(|(id, m)| (*id, m.role))
            .collect()
    }

    // ── Entrée ───────────────────────────────────────────────────────────

    /// `relation_to` : relation de `user` avec un compte donné (hôte ou participant).
    pub fn join<F: Fn(Uuid) -> Relation>(
        &mut self,
        user: Uuid,
        relation_to: F,
        invite_token: Option<&str>,
        now: DateTime<Utc>,
    ) -> Result<(), SessionError> {
        if self.closed || self.is_expired(now) {
            return Err(SessionError::Unavailable);
        }
        if self.members.contains_key(&user) {
            return Ok(());
        }
        // Banni de la session, ou bloqué avec l'hôte ou un participant : même réponse neutre.
        if self.banned.contains(&user) || self.members.keys().any(|m| relation_to(*m).blocked) {
            return Err(SessionError::Unavailable);
        }
        let host = self.host().ok_or(SessionError::Unavailable)?;
        let host_relation = relation_to(host);
        if !host_relation.visible {
            return Err(SessionError::Unavailable);
        }
        if self.locked {
            return Err(SessionError::Locked);
        }
        match self.access {
            Access::Friends => {
                if !host_relation.friend {
                    return Err(SessionError::Unavailable);
                }
            }
            Access::InviteOnly => {
                let token = invite_token.ok_or(SessionError::BadInvite)?;
                if !self.invite_valid(token, now) {
                    return Err(SessionError::BadInvite);
                }
            }
            Access::OpenWithLink => {}
        }
        if self.members.len() >= self.max_participants {
            return Err(SessionError::Full);
        }
        self.members.insert(user, Member { role: Role::Listener, joined_at: now, muted: false });
        Ok(())
    }

    fn invite_valid(&self, token: &str, now: DateTime<Utc>) -> bool {
        let h = hash_token(token);
        // Comparaison sur toutes les invitations, sans sortie anticipée sur le contenu.
        let mut ok = false;
        for i in &self.invites {
            let same = subtle::ConstantTimeEq::ct_eq(&i.token_hash[..], &h[..]).unwrap_u8() == 1;
            ok |= same && !i.revoked && now < i.expires_at;
        }
        ok
    }

    // ── Invitations ──────────────────────────────────────────────────────

    /// Seul l'hôte crée un lien d'invitation. Renvoie (identifiant, jeton en clair) :
    /// le jeton n'est jamais conservé, seulement son empreinte.
    pub fn create_invite(&mut self, actor: Uuid, ttl: Option<Duration>, now: DateTime<Utc>) -> Result<(Uuid, String), SessionError> {
        self.require_host(actor)?;
        let ttl = ttl.unwrap_or(DEFAULT_INVITE_TTL);
        if ttl <= Duration::zero() || ttl > MAX_INVITE_TTL {
            return Err(SessionError::BadTtl);
        }
        let token = random_token();
        let id = Uuid::new_v4();
        self.invites.retain(|i| !i.revoked && i.expires_at > now);
        self.invites.push(Invite { id, token_hash: hash_token(&token), expires_at: now + ttl, revoked: false });
        Ok((id, token))
    }

    pub fn revoke_invite(&mut self, actor: Uuid, id: Uuid) -> Result<(), SessionError> {
        self.require_host(actor)?;
        for i in &mut self.invites {
            if i.id == id {
                i.revoked = true;
            }
        }
        Ok(())
    }

    pub fn revoke_all_invites(&mut self, actor: Uuid) -> Result<(), SessionError> {
        self.require_host(actor)?;
        for i in &mut self.invites {
            i.revoked = true;
        }
        Ok(())
    }

    // ── Réglages de l'hôte ───────────────────────────────────────────────

    fn require_host(&self, actor: Uuid) -> Result<(), SessionError> {
        if self.role_of(actor) == Some(Role::Host) {
            Ok(())
        } else {
            Err(SessionError::NotAllowed)
        }
    }

    fn require_staff(&self, actor: Uuid) -> Result<Role, SessionError> {
        match self.role_of(actor) {
            Some(r) if r >= Role::Moderator => Ok(r),
            _ => Err(SessionError::NotAllowed),
        }
    }

    pub fn set_access(&mut self, actor: Uuid, access: Access) -> Result<(), SessionError> {
        self.require_host(actor)?;
        self.access = access;
        Ok(())
    }

    pub fn set_locked(&mut self, actor: Uuid, locked: bool) -> Result<(), SessionError> {
        self.require_host(actor)?;
        self.locked = locked;
        Ok(())
    }

    pub fn set_chat_enabled(&mut self, actor: Uuid, enabled: bool) -> Result<(), SessionError> {
        self.require_staff(actor)?;
        self.chat_enabled = enabled;
        Ok(())
    }

    pub fn set_max_participants(&mut self, actor: Uuid, max: usize) -> Result<(), SessionError> {
        self.require_host(actor)?;
        self.max_participants = max.clamp(self.members.len().max(2), MAX_PARTICIPANTS_LIMIT);
        Ok(())
    }

    pub fn set_permissions(&mut self, actor: Uuid, permissions: Permissions) -> Result<(), SessionError> {
        self.require_host(actor)?;
        self.permissions = permissions;
        Ok(())
    }

    pub fn set_moderator(&mut self, actor: Uuid, target: Uuid, moderator: bool) -> Result<(), SessionError> {
        self.require_host(actor)?;
        let m = self.members.get_mut(&target).ok_or(SessionError::NoSuchMember)?;
        if m.role == Role::Host {
            return Err(SessionError::NotAllowed);
        }
        m.role = if moderator { Role::Moderator } else { Role::Listener };
        Ok(())
    }

    /// Transfère le rôle d'hôte à un participant ; l'ancien hôte devient modérateur.
    pub fn transfer_host(&mut self, actor: Uuid, target: Uuid) -> Result<(), SessionError> {
        self.require_host(actor)?;
        if !self.members.contains_key(&target) {
            return Err(SessionError::NoSuchMember);
        }
        if target != actor {
            self.members.get_mut(&actor).unwrap().role = Role::Moderator;
            self.members.get_mut(&target).unwrap().role = Role::Host;
        }
        Ok(())
    }

    pub fn close(&mut self, actor: Uuid) -> Result<(), SessionError> {
        self.require_host(actor)?;
        self.wipe();
        Ok(())
    }

    /// Fermeture par l'équipe de Sona (modération), sans être participant.
    pub fn close_by_staff(&mut self) {
        self.wipe();
    }

    /// Données temporaires nettoyées : participants, bannis, invitations.
    fn wipe(&mut self) {
        self.closed = true;
        self.members.clear();
        self.banned.clear();
        self.invites.clear();
    }

    // ── Modération ───────────────────────────────────────────────────────

    /// Un modérateur ne touche ni à l'hôte ni à un autre modérateur.
    fn can_moderate(&self, actor: Uuid, target: Uuid) -> Result<(), SessionError> {
        let a = self.require_staff(actor)?;
        let t = self.role_of(target).ok_or(SessionError::NoSuchMember)?;
        if actor == target || t >= a {
            return Err(SessionError::NotAllowed);
        }
        Ok(())
    }

    pub fn kick(&mut self, actor: Uuid, target: Uuid) -> Result<(), SessionError> {
        self.can_moderate(actor, target)?;
        self.members.remove(&target);
        Ok(())
    }

    /// Expulse ET interdit de revenir dans cette session.
    pub fn ban(&mut self, actor: Uuid, target: Uuid) -> Result<(), SessionError> {
        self.can_moderate(actor, target)?;
        self.members.remove(&target);
        self.banned.insert(target);
        Ok(())
    }

    pub fn set_muted(&mut self, actor: Uuid, target: Uuid, muted: bool) -> Result<(), SessionError> {
        self.can_moderate(actor, target)?;
        self.members.get_mut(&target).unwrap().muted = muted;
        Ok(())
    }

    /// Sort volontairement. Si c'est l'hôte : le rôle passe au plus ancien
    /// modérateur, sinon au plus ancien participant, sinon la session se ferme.
    pub fn leave(&mut self, user: Uuid) {
        let Some(me) = self.members.remove(&user) else { return };
        if me.role == Role::Host {
            let next = self
                .members
                .iter()
                .max_by_key(|(_, m)| (m.role, std::cmp::Reverse(m.joined_at)))
                .map(|(id, _)| *id);
            match next {
                Some(id) => self.members.get_mut(&id).unwrap().role = Role::Host,
                None => self.wipe(),
            }
        }
    }

    /// Un blocage entre deux participants : celui qui n'est pas l'hôte sort.
    /// (Si les deux ne sont pas l'hôte, c'est la personne bloquée qui sort.)
    pub fn on_block(&mut self, blocker: Uuid, blocked: Uuid) {
        if self.role_of(blocked) == Some(Role::Host) {
            self.members.remove(&blocker);
        } else {
            self.members.remove(&blocked);
        }
    }

    // ── Droits d'usage ───────────────────────────────────────────────────

    pub fn can(&self, user: Uuid, action: Action) -> bool {
        let Some(m) = self.members.get(&user) else { return false };
        if self.closed {
            return false;
        }
        let who = match action {
            Action::AddTracks => self.permissions.add_tracks,
            Action::ChangeTrack => self.permissions.change_track,
            Action::Pause => self.permissions.pause,
        };
        match who {
            Who::Everyone => true,
            Who::Moderators => m.role >= Role::Moderator,
            Who::Host => m.role == Role::Host,
        }
    }

    pub fn can_chat(&self, user: Uuid) -> bool {
        !self.closed && self.chat_enabled && self.members.get(&user).map(|m| !m.muted).unwrap_or(false)
    }

    /// Suppression d'un message : l'hôte et les modérateurs (pas l'auteur ici).
    pub fn can_delete_messages(&self, user: Uuid) -> bool {
        self.role_of(user).map(|r| r >= Role::Moderator).unwrap_or(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id() -> Uuid {
        Uuid::new_v4()
    }
    fn t0() -> DateTime<Utc> {
        DateTime::parse_from_rfc3339("2026-11-26T12:00:00Z").unwrap().with_timezone(&Utc)
    }
    fn friend(_: Uuid) -> Relation {
        Relation { friend: true, blocked: false, visible: true }
    }
    fn stranger(_: Uuid) -> Relation {
        Relation { friend: false, blocked: false, visible: true }
    }

    #[test]
    fn new_session_is_private_by_default() {
        let host = id();
        let mut s = Session::new("ABCD", host, t0());
        assert_eq!(s.access, Access::Friends);
        assert!(!s.locked);
        let outsider = id();
        assert_eq!(s.join(outsider, stranger, None, t0()), Err(SessionError::Unavailable));
        assert!(s.join(id(), friend, None, t0()).is_ok());
    }

    #[test]
    fn open_with_link_is_opt_in() {
        let host = id();
        let mut s = Session::new("ABCD", host, t0());
        let guest = id();
        assert!(s.join(guest, stranger, None, t0()).is_err());
        s.set_access(host, Access::OpenWithLink).unwrap();
        assert!(s.join(guest, stranger, None, t0()).is_ok());
        assert_eq!(s.set_access(guest, Access::Friends), Err(SessionError::NotAllowed));
    }

    #[test]
    fn invite_tokens_expire_and_can_be_revoked() {
        let host = id();
        let mut s = Session::new("ABCD", host, t0());
        s.set_access(host, Access::InviteOnly).unwrap();
        let (invite_id, token) = s.create_invite(host, Some(Duration::minutes(10)), t0()).unwrap();
        assert_eq!(s.join(id(), stranger, None, t0()), Err(SessionError::BadInvite));
        assert_eq!(s.join(id(), stranger, Some("faux"), t0()), Err(SessionError::BadInvite));
        assert!(s.join(id(), stranger, Some(&token), t0() + Duration::minutes(9)).is_ok());
        assert_eq!(s.join(id(), stranger, Some(&token), t0() + Duration::minutes(11)), Err(SessionError::BadInvite));
        s.revoke_invite(host, invite_id).unwrap();
        assert_eq!(s.join(id(), stranger, Some(&token), t0() + Duration::minutes(1)), Err(SessionError::BadInvite));
    }

    #[test]
    fn invite_ttl_is_bounded_and_host_only() {
        let host = id();
        let mut s = Session::new("ABCD", host, t0());
        let guest = id();
        s.set_access(host, Access::OpenWithLink).unwrap();
        s.join(guest, stranger, None, t0()).unwrap();
        assert_eq!(s.create_invite(guest, None, t0()), Err(SessionError::NotAllowed));
        assert_eq!(s.create_invite(host, Some(Duration::days(30)), t0()), Err(SessionError::BadTtl));
        assert_eq!(s.create_invite(host, Some(Duration::zero()), t0()), Err(SessionError::BadTtl));
        assert!(s.create_invite(host, None, t0()).is_ok());
    }

    #[test]
    fn tokens_are_stored_hashed_only() {
        let host = id();
        let mut s = Session::new("ABCD", host, t0());
        let (_, token) = s.create_invite(host, None, t0()).unwrap();
        assert_eq!(token.len(), 48);
        assert!(!format!("{s:?}").contains(&token));
    }

    #[test]
    fn locked_expired_closed_and_full_refuse_newcomers() {
        let host = id();
        let mut s = Session::new("ABCD", host, t0());
        s.set_locked(host, true).unwrap();
        assert_eq!(s.join(id(), friend, None, t0()), Err(SessionError::Locked));
        s.set_locked(host, false).unwrap();
        assert!(s.join(id(), friend, None, t0() + SESSION_LIFETIME + Duration::seconds(1)).is_err(), "expirée");

        let mut full = Session::new("EFGH", host, t0());
        full.set_max_participants(host, 2).unwrap();
        assert!(full.join(id(), friend, None, t0()).is_ok());
        assert_eq!(full.join(id(), friend, None, t0()), Err(SessionError::Full));

        let mut closed = Session::new("IJKL", host, t0());
        closed.close(host).unwrap();
        assert_eq!(closed.join(id(), friend, None, t0()), Err(SessionError::Unavailable));
    }

    #[test]
    fn blocked_users_cannot_join_and_get_a_neutral_error() {
        let host = id();
        let mut s = Session::new("ABCD", host, t0());
        s.set_access(host, Access::OpenWithLink).unwrap();
        let blocked = |_: Uuid| Relation { friend: false, blocked: true, visible: true };
        assert_eq!(s.join(id(), blocked, None, t0()), Err(SessionError::Unavailable));
        // Même message qu'une session inexistante ou un bannissement : rien ne fuit.
        assert_eq!(SessionError::Unavailable.to_string(), "Cette session n'est pas disponible.");
    }

    #[test]
    fn blocked_participants_are_invisible_to_each_other() {
        let host = id();
        let (a, b) = (id(), id());
        let mut s = Session::new("ABCD", host, t0());
        s.set_access(host, Access::OpenWithLink).unwrap();
        s.join(a, stranger, None, t0()).unwrap();
        s.join(b, stranger, None, t0()).unwrap();
        let view = s.visible_members(a, |other| Relation { friend: false, blocked: other == b, visible: true });
        let ids: Vec<Uuid> = view.iter().map(|(i, _)| *i).collect();
        assert!(ids.contains(&a) && ids.contains(&host) && !ids.contains(&b));
    }

    #[test]
    fn suspended_or_banned_host_makes_the_session_unreachable() {
        let host = id();
        let mut s = Session::new("ABCD", host, t0());
        let hidden = |_: Uuid| Relation { friend: true, blocked: false, visible: false };
        assert_eq!(s.join(id(), hidden, None, t0()), Err(SessionError::Unavailable));
    }

    #[test]
    fn kick_allows_return_ban_does_not() {
        let host = id();
        let guest = id();
        let mut s = Session::new("ABCD", host, t0());
        s.join(guest, friend, None, t0()).unwrap();
        s.kick(host, guest).unwrap();
        assert!(!s.is_member(guest));
        assert!(s.join(guest, friend, None, t0()).is_ok());
        s.ban(host, guest).unwrap();
        assert_eq!(s.join(guest, friend, None, t0()), Err(SessionError::Unavailable));
    }

    #[test]
    fn moderators_are_limited() {
        let (host, modo, a, b) = (id(), id(), id(), id());
        let mut s = Session::new("ABCD", host, t0());
        for u in [modo, a, b] {
            s.join(u, friend, None, t0()).unwrap();
        }
        s.set_moderator(host, modo, true).unwrap();
        assert_eq!(s.kick(modo, host), Err(SessionError::NotAllowed));
        assert_eq!(s.kick(a, b), Err(SessionError::NotAllowed));
        assert!(s.kick(modo, a).is_ok());
        assert_eq!(s.set_locked(modo, true), Err(SessionError::NotAllowed));
        assert_eq!(s.create_invite(modo, None, t0()).err(), Some(SessionError::NotAllowed));
        assert_eq!(s.close(modo), Err(SessionError::NotAllowed));
        assert!(s.set_chat_enabled(modo, false).is_ok());
        assert!(!s.can_chat(b));
    }

    #[test]
    fn permissions_follow_settings() {
        let (host, modo, guest) = (id(), id(), id());
        let mut s = Session::new("ABCD", host, t0());
        s.join(modo, friend, None, t0()).unwrap();
        s.join(guest, friend, None, t0()).unwrap();
        s.set_moderator(host, modo, true).unwrap();
        assert!(s.can(guest, Action::AddTracks));
        assert!(!s.can(guest, Action::ChangeTrack));
        assert!(s.can(modo, Action::Pause));
        s.set_permissions(host, Permissions { add_tracks: Who::Host, change_track: Who::Host, pause: Who::Everyone }).unwrap();
        assert!(!s.can(guest, Action::AddTracks));
        assert!(!s.can(modo, Action::ChangeTrack));
        assert!(s.can(guest, Action::Pause));
        assert!(!s.can(id(), Action::Pause), "un inconnu ne peut rien");
    }

    #[test]
    fn transfer_and_leave_keep_a_host() {
        let (host, a, b) = (id(), id(), id());
        let mut s = Session::new("ABCD", host, t0());
        s.join(a, friend, None, t0()).unwrap();
        s.join(b, friend, None, t0() + Duration::minutes(1)).unwrap();
        s.transfer_host(host, a).unwrap();
        assert_eq!(s.host(), Some(a));
        assert_eq!(s.role_of(host), Some(Role::Moderator));
        assert_eq!(s.transfer_host(host, b), Err(SessionError::NotAllowed));
        s.leave(a);
        assert_eq!(s.host(), Some(host), "le modérateur reprend la main");
        s.leave(host);
        assert_eq!(s.host(), Some(b));
        s.leave(b);
        assert!(s.closed);
    }

    #[test]
    fn closing_wipes_temporary_data() {
        let host = id();
        let mut s = Session::new("ABCD", host, t0());
        let (_, token) = s.create_invite(host, None, t0()).unwrap();
        s.join(id(), friend, None, t0()).unwrap();
        s.close(host).unwrap();
        assert_eq!(s.participant_count(), 0);
        assert!(!s.invite_valid(&token, t0()));
        assert!(!s.can(host, Action::Pause));
    }

    #[test]
    fn block_between_participants_removes_the_right_one() {
        let (host, a, b) = (id(), id(), id());
        let mut s = Session::new("ABCD", host, t0());
        s.join(a, friend, None, t0()).unwrap();
        s.join(b, friend, None, t0()).unwrap();
        s.on_block(a, b);
        assert!(s.is_member(a) && !s.is_member(b));
        s.on_block(a, host);
        assert!(!s.is_member(a), "bloquer l'hôte = quitter sa session");
    }

    #[test]
    fn capacity_never_exceeds_the_hard_limit() {
        let host = id();
        let mut s = Session::new("ABCD", host, t0());
        s.set_max_participants(host, 10_000).unwrap();
        assert_eq!(s.max_participants, MAX_PARTICIPANTS_LIMIT);
    }
}
