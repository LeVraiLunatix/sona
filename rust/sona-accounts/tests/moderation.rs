//! Tests SQL : bannissements, hiérarchie des rôles, audit, signalements,
//! anti-abus à l'inscription, pseudos, rétention, export.

mod common;
use common::{db_message, sqlstate, Who};
use serde_json::json;

fn u(id: uuid::Uuid) -> Who {
    Who::User(id)
}

async fn staff(db: &common::TestDb, name: &str, role: &str) -> uuid::Uuid {
    let id = db.named(name).await;
    db.make_role(id, role).await;
    id
}

#[tokio::test]
async fn a_banned_user_is_refused_immediately_even_with_an_open_session() {
    let db = db_or_skip!();
    let admin = staff(&db, "boss", "admin").await;
    let a = db.named("troll").await;
    let b = db.named("gentil").await;
    db.friends(a, b).await;
    db.privacy(a, "presence_visibility = 'everyone'").await;
    db.su(&format!("insert into auth.sessions (user_id) values ('{a}'), ('{a}')")).await;
    assert_eq!(db.su_scalar(&format!("select count(*) from auth.sessions where user_id = '{a}'")).await, "2");
    // Avant : tout fonctionne.
    db.x(u(a), &format!("update public.profiles set bio = 'avant' where id = '{a}'")).await.unwrap();
    assert!(db.q(u(b), &format!("select public.can_i_view('{a}', 'presence') as v")).await.unwrap()[0]["v"].as_bool().unwrap());

    db.x(Who::Service, &format!("select public.admin_sanction('{admin}', '{a}', 'ban', 'harcèlement répété')")).await.unwrap();

    // Même jeton, même « session » : plus rien ne passe, sans attendre l'expiration du JWT.
    assert_eq!(db.x(u(a), &format!("update public.profiles set bio = 'après' where id = '{a}'")).await.unwrap(), 0);
    assert_eq!(db.su_scalar(&format!("select bio from public.profiles where id = '{a}'")).await, "avant");
    assert_eq!(db.x(u(a), "select public.send_friend_request('gentil')").await.unwrap_err().to_string().contains("forbidden"), true);
    assert_eq!(db.x(u(a), "update public.user_settings set theme = 'dark'").await.unwrap(), 0);
    assert_eq!(db.x(u(a), "update public.privacy_settings set presence_visibility = 'nobody'").await.unwrap(), 0);
    assert!(db.x(u(a), &format!("select public.block_user('{b}')")).await.is_err());
    // Il disparaît des listes d'amis et de toute visibilité.
    assert_eq!(db.count(u(b), "select * from public.list_friends()").await, 0);
    for s in ["presence", "profile_min", "history"] {
        assert_eq!(db.q(u(b), &format!("select public.can_i_view('{a}', '{s}') as v")).await.unwrap()[0]["v"], false);
    }
    assert_eq!(db.q(u(b), &format!("select public.get_profile('{a}') as p")).await.unwrap()[0]["p"], json!(null));
    // Ses sessions sont fermées.
    assert_eq!(db.su_scalar(&format!("select count(*) from auth.sessions where user_id = '{a}'")).await, "0");
    // Il voit son statut, la raison, et peut contester ou exporter ses données.
    let me = db.q(u(a), "select status::text, status_reason from public.profiles").await.unwrap();
    assert_eq!(me, json!([{ "status": "banned", "status_reason": "harcèlement répété" }]));
    let sanction: String = db.su_scalar(&format!("select id from public.sanctions where user_id = '{a}'")).await;
    assert_eq!(db.count(u(a), "select * from public.sanctions where kind = 'ban'").await, 1);
    db.x(u(a), &format!("select public.create_appeal('{sanction}', 'je ne le referai plus')")).await.unwrap();
    assert_eq!(db.count(u(a), "select * from public.appeals").await, 1);
    let export = db.q(u(a), "select public.export_my_data() as d").await.unwrap();
    assert!(export[0]["d"]["sanctions"].as_array().unwrap().len() == 1);
}

#[tokio::test]
async fn a_banned_identity_cannot_sign_up_again() {
    let db = db_or_skip!();
    let admin = staff(&db, "boss", "admin").await;
    let a = db.user("Jean.Dupont+test@gmail.com").await;
    db.su(&format!("insert into auth.identities (user_id, provider, provider_id) values ('{a}', 'discord', '9988')")).await;
    db.x(Who::Service, &format!("select public.admin_sanction('{admin}', '{a}', 'ban', 'spam massif')")).await.unwrap();
    // Même e-mail, variantes gmail (points, +alias, casse) : refusés.
    for email in ["jeandupont@gmail.com", "JEAN.DUPONT@googlemail.com", "j.e.a.n.dupont+autre@gmail.com"] {
        let e = sqlx::query("insert into auth.users (email) values ($1)").bind(email).execute(&db.pool).await.unwrap_err();
        assert!(db_message(&e).starts_with("signup_blocked:banned"), "{email} → {}", db_message(&e));
    }
    // Même identifiant OAuth avec un autre e-mail : refusé.
    let e = sqlx::query("insert into auth.users (email, raw_app_meta_data, raw_user_meta_data) values ('autre@example.test', '{\"provider\":\"discord\"}', '{\"provider_id\":\"9988\"}')")
        .execute(&db.pool).await.unwrap_err();
    assert!(db_message(&e).starts_with("signup_blocked:banned"));
    // Un autre compte Discord passe.
    sqlx::query("insert into auth.users (email, raw_app_meta_data, raw_user_meta_data) values ('ok@example.test', '{\"provider\":\"discord\"}', '{\"provider_id\":\"1111\"}')")
        .execute(&db.pool).await.unwrap();
    // Lever le ban rouvre l'inscription.
    db.x(Who::Service, &format!("select public.admin_lift('{admin}', '{a}', 'erreur de ma part')")).await.unwrap();
    sqlx::query("insert into auth.users (email) values ('jeandupont@gmail.com')").execute(&db.pool).await.unwrap();
}

#[tokio::test]
async fn disposable_domains_ips_and_bursts_are_blocked() {
    let db = db_or_skip!();
    let e = sqlx::query("insert into auth.users (email) values ('x@mailinator.com')").execute(&db.pool).await.unwrap_err();
    assert_eq!(db_message(&e), "signup_blocked:disposable_email");
    let admin = staff(&db, "boss", "admin").await;
    db.x(Who::Service, &format!("select public.admin_ban_identifier('{admin}', 'email_domain', 'poubelle.test', 'domaine abusif')")).await.unwrap();
    assert!(sqlx::query("insert into auth.users (email) values ('x@poubelle.test')").execute(&db.pool).await.is_err());
    // Hook (avec IP) : 5 inscriptions acceptées par heure, puis blocage + alerte.
    for i in 0..5 {
        let r = db.q(Who::Service, &format!("select public.signup_guard('u{i}@example.test', 'email', null, '203.0.113.7') as r")).await.unwrap();
        assert_eq!(r[0]["r"], json!(null));
    }
    let r = db.q(Who::Service, "select public.signup_guard('u9@example.test', 'email', null, '203.0.113.7') as r").await.unwrap();
    assert_eq!(r[0]["r"], "ip_burst");
    assert_eq!(db.count(Who::Service, "select * from public.admin_alerts where kind = 'signup_burst'").await, 1);
    // Une autre IP n'est pas touchée ; une IP bannie (plage) l'est.
    assert_eq!(db.q(Who::Service, "select public.signup_guard('v@example.test', 'email', null, '198.51.100.1') as r").await.unwrap()[0]["r"], json!(null));
    db.x(Who::Service, &format!("select public.admin_ban_identifier('{admin}', 'ip', '192.0.2.0/24', 'attaque', interval '1 day')")).await.unwrap();
    assert_eq!(db.q(Who::Service, "select public.signup_guard('w@example.test', 'email', null, '192.0.2.55') as r").await.unwrap()[0]["r"], "ip_blocked");
    // Seul le rôle serveur appelle le hook.
    let b = db.named("curieux").await;
    assert!(db.q(u(b), "select public.signup_guard('a@b.test', 'email', null, '1.2.3.4')").await.is_err());
}

#[tokio::test]
async fn role_hierarchy_reason_and_durations_are_enforced_by_the_database() {
    let db = db_or_skip!();
    let admin = staff(&db, "boss", "admin").await;
    let admin2 = staff(&db, "boss2", "admin").await;
    let modo = staff(&db, "modo", "moderator").await;
    let user = db.named("quidam").await;
    let other = db.named("autre").await;
    let s = Who::Service;
    // Motif obligatoire.
    for reason in ["", "  ", "ab"] {
        let e = db.x(s, &format!("select public.admin_sanction('{admin}', '{user}', 'warning', '{reason}')")).await.unwrap_err();
        assert_eq!(db_message(&e), "reason_required");
    }
    // Un utilisateur ou un acteur inconnu ne peut rien.
    let e = db.x(s, &format!("select public.admin_sanction('{user}', '{other}', 'warning', 'motif valable')")).await.unwrap_err();
    assert_eq!(sqlstate(&e), "42501");
    // Le modérateur peut avertir, suspendre ≤ 7 jours, pas bannir ni suspendre plus longtemps.
    db.x(s, &format!("select public.admin_sanction('{modo}', '{user}', 'warning', 'premier avertissement')")).await.unwrap();
    db.x(s, &format!("select public.admin_sanction('{modo}', '{user}', 'warning', 'second avertissement')")).await.unwrap();
    assert_eq!(db.count(u(user), "select * from public.sanctions where kind = 'warning'").await, 2);
    assert_eq!(db.count(u(user), "select * from public.notifications where kind = 'warning'").await, 2);
    assert_eq!(db.su_scalar(&format!("select status from public.profiles where id = '{user}'")).await, "active", "un avertissement ne sanctionne pas le compte");
    let e = db.x(s, &format!("select public.admin_sanction('{modo}', '{user}', 'ban', 'motif valable')")).await.unwrap_err();
    assert_eq!(sqlstate(&e), "42501");
    let e = db.x(s, &format!("select public.admin_sanction('{modo}', '{user}', 'suspension', 'motif valable', interval '30 days')")).await.unwrap_err();
    assert_eq!(db_message(&e), "duration_too_long_for_moderator");
    let e = db.x(s, &format!("select public.admin_sanction('{modo}', '{user}', 'suspension', 'motif valable')")).await.unwrap_err();
    assert_eq!(db_message(&e), "duration_required");
    db.x(s, &format!("select public.admin_sanction('{modo}', '{user}', 'suspension', 'calme-toi', interval '24 hours')")).await.unwrap();
    assert_eq!(db.su_scalar(&format!("select status from public.profiles where id = '{user}'")).await, "suspended");
    // Le modérateur ne touche ni à un admin, ni à un autre modérateur, ni à lui-même.
    for target in [admin, modo] {
        assert!(db.x(s, &format!("select public.admin_sanction('{modo}', '{target}', 'warning', 'motif valable')")).await.is_err());
    }
    // Ni un admin à un autre admin ni à lui-même.
    assert!(db.x(s, &format!("select public.admin_sanction('{admin}', '{admin2}', 'ban', 'motif valable')")).await.is_err());
    assert!(db.x(s, &format!("select public.admin_sanction('{admin}', '{admin}', 'ban', 'motif valable')")).await.is_err());
    // Rôles : réservé aux admins, jamais soi-même, jamais le dernier admin.
    assert!(db.x(s, &format!("select public.admin_set_role('{modo}', '{user}', 'moderator', 'promotion')")).await.is_err());
    assert!(db.x(s, &format!("select public.admin_set_role('{admin}', '{admin}', 'user', 'moi')")).await.is_err());
    db.x(s, &format!("select public.admin_set_role('{admin}', '{user}', 'moderator', 'bon travail')")).await.unwrap();
    db.x(s, &format!("select public.admin_set_role('{admin}', '{admin2}', 'user', 'rétrogradation')")).await.unwrap();
    let e = db.x(s, &format!("select public.admin_set_role('{user}', '{admin}', 'user', 'coup d etat')")).await.unwrap_err();
    assert_eq!(sqlstate(&e), "42501");
    // Un modérateur ne lève pas un ban.
    db.x(s, &format!("select public.admin_sanction('{admin}', '{other}', 'ban', 'abus grave')")).await.unwrap();
    let e = db.x(s, &format!("select public.admin_lift('{modo}', '{other}', 'pitié')")).await.unwrap_err();
    assert_eq!(db_message(&e), "ban_requires_admin");
    db.x(s, &format!("select public.admin_lift('{admin}', '{other}', 'appel accepté')")).await.unwrap();
    assert_eq!(db.su_scalar(&format!("select status from public.profiles where id = '{other}'")).await, "active");
}

#[tokio::test]
async fn temporary_suspensions_expire_by_themselves() {
    let db = db_or_skip!();
    let admin = staff(&db, "boss", "admin").await;
    let a = db.named("agite").await;
    db.named("copain").await;
    db.x(Who::Service, &format!("select public.admin_sanction('{admin}', '{a}', 'suspension', 'une heure de calme', interval '1 hour')")).await.unwrap();
    assert!(db.x(u(a), "select public.send_friend_request('copain')").await.is_err());
    // L'heure passe : le statut réel redevient actif sans attendre la tâche planifiée.
    db.su(&format!("update public.profiles set status_until = now() - interval '1 minute' where id = '{a}'")).await;
    db.x(u(a), "select public.send_friend_request('copain')").await.unwrap();
    db.x(Who::Service, "select public.purge_expired()").await.unwrap();
    assert_eq!(db.su_scalar(&format!("select status from public.profiles where id = '{a}'")).await, "active");
}

#[tokio::test]
async fn the_audit_log_is_append_only_and_admin_readable() {
    let db = db_or_skip!();
    let admin = staff(&db, "boss", "admin").await;
    let modo = staff(&db, "modo", "moderator").await;
    let a = db.named("fautif").await;
    db.x(Who::Service, &format!("select public.admin_sanction('{modo}', '{a}', 'warning', 'langage déplacé')")).await.unwrap();
    db.x(Who::Service, &format!("select public.admin_reset_profile('{modo}', '{a}', array['username','bio'], false, 'pseudo offensant')")).await.unwrap();
    let rows = db.q(u(admin), "select action, reason, actor_role from public.audit_log order by id").await.unwrap();
    assert_eq!(rows[0]["action"], "sanction.warning");
    assert_eq!(rows[0]["actor_role"], "moderator");
    assert_eq!(rows[1]["action"], "profile.reset");
    assert_eq!(rows[1]["reason"], "pseudo offensant");
    // Lisible seulement par les admins.
    assert_eq!(db.count(u(modo), "select * from public.audit_log").await, 0);
    assert_eq!(db.count(u(a), "select * from public.audit_log").await, 0);
    assert!(db.q(Who::Anon, "select * from public.audit_log").await.is_err());
    // Non modifiable, non supprimable : ni client, ni service, ni propriétaire.
    for who in [u(admin), Who::Service] {
        assert!(db.x(who, "update public.audit_log set reason = 'effacé'").await.is_err());
        assert!(db.x(who, "delete from public.audit_log").await.is_err());
        assert!(db.x(who, "truncate public.audit_log").await.is_err());
    }
    let e = sqlx::query("delete from public.audit_log").execute(&db.pool).await.unwrap_err();
    assert_eq!(db_message(&e), "audit_log_immutable");
    assert!(sqlx::query("update public.audit_log set action = 'x'").execute(&db.pool).await.is_err());
    // Seule la purge de rétention (> 12 mois) supprime.
    db.su("insert into public.audit_log (at, action) values (now() - interval '13 months', 'vieux')").await;
    db.x(Who::Service, "select public.purge_expired()").await.unwrap();
    assert_eq!(db.su_scalar("select count(*) from public.audit_log where action = 'vieux'").await, "0");
    assert_eq!(db.su_scalar("select count(*) from public.audit_log where action = 'sanction.warning'").await, "1");
}

#[tokio::test]
async fn admin_reads_are_for_staff_only_and_emails_are_masked_for_moderators() {
    let db = db_or_skip!();
    let admin = staff(&db, "boss", "admin").await;
    let modo = staff(&db, "modo", "moderator").await;
    let a = db.named("lambda").await;
    for who in [u(a), Who::Anon] {
        assert!(db.q(who, "select * from public.admin_list_users()").await.is_err());
        assert!(db.q(who, "select public.admin_dashboard()").await.is_err());
    }
    assert_eq!(db.count(u(a), "select * from public.reports").await, 0);
    let full = db.q(u(admin), "select username, email, providers from public.admin_list_users('lambda')").await.unwrap();
    assert_eq!(full[0]["email"], "lambda@example.test");
    let masked = db.q(u(modo), "select email from public.admin_list_users('lambda')").await.unwrap();
    assert_eq!(masked[0]["email"], "l***@example.test");
    // Recherche par identifiant et filtres.
    assert_eq!(db.count(u(admin), &format!("select * from public.admin_list_users('{a}')")).await, 1);
    assert_eq!(db.count(u(admin), "select * from public.admin_list_users(null, 'moderator')").await, 1);
    assert_eq!(db.count(u(admin), "select * from public.admin_list_users(null, null, 'banned')").await, 0);
    assert_eq!(db.count(u(admin), "select * from public.admin_list_users('example.test')").await, 3);
    // Un compte sanctionné perd ses droits d'équipe immédiatement.
    let boss2 = staff(&db, "boss2", "admin").await;
    db.su(&format!("update public.profiles set status = 'suspended', status_until = now() + interval '1 day' where id = '{boss2}'")).await;
    assert!(db.q(u(boss2), "select public.admin_dashboard()").await.is_err());
    let d = db.q(u(admin), "select public.admin_dashboard() as d").await.unwrap();
    assert_eq!(d[0]["d"]["total_users"], 4);
    assert_eq!(d[0]["d"]["suspended"], 1);
    assert_eq!(d[0]["d"]["signups_per_day"].as_array().unwrap().len(), 14);
    let detail = db.q(u(admin), &format!("select public.admin_user_detail('{a}') as d")).await.unwrap();
    assert!(detail[0]["d"]["profile"].get("friend_code").is_none());
}

#[tokio::test]
async fn reports_are_rate_limited_deduplicated_and_auto_quarantine() {
    let db = db_or_skip!();
    let admin = staff(&db, "boss", "admin").await;
    let target = db.named("cible").await;
    let mut reporters = vec![];
    for i in 0..5 {
        reporters.push(db.named(&format!("signaleur{i}")).await);
    }
    let r0 = reporters[0];
    let rep = |who: uuid::Uuid, reason: &str| format!("select public.create_report('profile', '{target}', null, '{reason}', 'texte') as id");
    let id1 = db.q(u(r0), &rep(r0, "spam")).await.unwrap()[0]["id"].clone();
    // Doublon dans les 24 h : même signalement.
    let id2 = db.q(u(r0), &rep(r0, "spam")).await.unwrap()[0]["id"].clone();
    assert_eq!(id1, id2);
    // On ne se signale pas soi-même.
    let e = db.x(u(r0), &format!("select public.create_report('profile', '{r0}', null, 'spam', null)")).await.unwrap_err();
    assert_eq!(sqlstate(&e), "22023");
    // 3 par heure.
    for n in 0..2 {
        db.x(u(r0), &format!("select public.create_report('message', '{target}', 'msg-{n}', 'harassment', null, '{{\"text\":\"mot\"}}')")).await.unwrap();
    }
    let e = db.x(u(r0), &format!("select public.create_report('message', '{target}', 'msg-9', 'harassment', null)")).await.unwrap_err();
    assert_eq!(db_message(&e), "rate_limited");
    // Le signalant ne voit que les siens ; l'inconnu rien ; la cible rien.
    assert_eq!(db.count(u(r0), "select * from public.reports").await, 3);
    assert_eq!(db.count(u(reporters[1]), "select * from public.reports").await, 0);
    assert_eq!(db.count(u(target), "select * from public.reports").await, 0);
    // Snapshot conservé.
    assert_eq!(db.su_scalar("select snapshot->>'text' from public.reports where target_ref = 'msg-0'").await, "mot");
    // Un signalement = une alerte pour l'équipe.
    assert!(db.count(Who::Service, "select * from public.admin_alerts where kind = 'new_report'").await >= 3);
    // 5 personnes différentes en 7 jours : quarantaine automatique.
    for r in &reporters[1..] {
        db.x(u(*r), &format!("select public.create_report('profile', '{target}', null, 'spam', null)")).await.unwrap();
    }
    assert_eq!(db.su_scalar(&format!("select status from public.profiles where id = '{target}'")).await, "quarantined");
    assert_eq!(db.count(Who::Service, "select * from public.admin_alerts where kind = 'auto_quarantine'").await, 1);
    assert_eq!(db.count(u(admin), "select * from public.audit_log where action = 'sanction.auto_quarantine'").await, 1);
    // En quarantaine : invisible des autres, ne peut pas solliciter, mais garde son compte.
    assert_eq!(db.q(u(r0), &format!("select public.get_profile('{target}') as p")).await.unwrap()[0]["p"], json!(null));
    assert!(db.x(u(target), "select public.send_friend_request('signaleur0')").await.is_err());
    assert_eq!(db.x(u(target), &format!("update public.profiles set bio = 'je suis encore là' where id = '{target}'")).await.unwrap(), 1);
    // L'admin tranche : action en un clic depuis le signalement, le signalant est prévenu.
    let report: String = db.su_scalar("select id from public.reports where reporter_id = (select id from public.profiles where username = 'signaleur1')").await;
    db.x(Who::Service, &format!("select public.admin_sanction('{admin}', '{target}', 'suspension', 'spam avéré', interval '7 days', '{report}')")).await.unwrap();
    assert_eq!(db.su_scalar(&format!("select status from public.reports where id = '{report}'")).await, "resolved");
    db.x(Who::Service, &format!("select public.staff_update_report('{admin}', '{report}', 'resolved', null, 'traité', 'rien à ajouter')")).await.unwrap();
    db.x(Who::Service, &format!("select public.staff_update_report('{admin}', '{}', 'dismissed', '{admin}', 'infondé', null)", db.su_scalar("select id from public.reports where target_ref = 'msg-0'").await)).await.unwrap();
    assert_eq!(db.count(u(r0), "select * from public.notifications where kind = 'report_update'").await, 1);
    assert_eq!(db.count(u(admin), "select * from public.report_notes").await, 1);
    assert_eq!(db.count(u(r0), "select * from public.report_notes").await, 0);
}

#[tokio::test]
async fn usernames_are_validated_server_side() {
    let db = db_or_skip!();
    let a = db.named("alice").await;
    let b = db.named("bob").await;
    let set = |name: &str| format!("update public.profiles set username = '{name}' where id = '{a}'");
    for (bad, why) in [
        ("ab", "23514"), ("trop_long_trop_long_trop_long", "23514"), ("avec espace", "23514"), ("emoji😀", "23514"),
        ("Admin", "23514"), ("m0d3r4t3ur", "23514"), ("Hitler_fan", "23514"), ("H1TL3R", "23514"), ("su-pp-ort", "23514"),
        ("BOB", "23505"), ("bob", "23505"),
    ] {
        let e = db.x(u(a), &set(bad)).await.unwrap_err();
        assert_eq!(sqlstate(&e), why, "{bad}");
    }
    db.x(u(a), &set("Alice.Dupont_92")).await.unwrap();
    assert_eq!(db.su_scalar(&format!("select username from public.profiles where id = '{a}'")).await, "Alice.Dupont_92");
    // Vérification en direct : raison précise, y compris pour un anonyme (inscription).
    let r = |name: &str| format!("select public.username_available('{name}') as r");
    assert_eq!(db.q(Who::Anon, &r("libre_123")).await.unwrap()[0]["r"], json!({ "available": true }));
    assert_eq!(db.q(Who::Anon, &r("BoB")).await.unwrap()[0]["r"], json!({ "available": false, "reason": "taken" }));
    assert_eq!(db.q(Who::Anon, &r("admin")).await.unwrap()[0]["r"]["reason"], "reserved");
    assert_eq!(db.q(Who::Anon, &r("nazism")).await.unwrap()[0]["r"]["reason"], "offensive");
    assert_eq!(db.q(Who::Anon, &r("a")).await.unwrap()[0]["r"]["reason"], "format");
    // Les prénoms courants ne sont pas pris pour des insultes.
    for ok in ["dominique", "nazim", "torpedo", "skyscraper", "monkeys"] {
        assert_eq!(db.q(Who::Anon, &r(ok)).await.unwrap()[0]["r"]["available"], true, "{ok}");
    }
    // Pas d'énumération à la chaîne : 40 appels par minute.
    let mut blocked = false;
    for i in 0..45 {
        if db.q(u(b), &r(&format!("essai{i}"))).await.is_err() {
            blocked = true;
        }
    }
    assert!(blocked, "limite de débit sur la vérification de pseudo");
    // Photo : https seulement.
    assert!(db.x(u(b), &format!("update public.profiles set avatar_url = 'http://x.test/a.png' where id = '{b}'")).await.is_err());
    assert!(db.x(u(b), &format!("update public.profiles set avatar_url = 'javascript:alert(1)' where id = '{b}'")).await.is_err());
    db.x(u(b), &format!("update public.profiles set avatar_url = 'https://x.test/a.png' where id = '{b}'")).await.unwrap();
}

#[tokio::test]
async fn owned_names_are_for_their_owner_only() {
    let db = db_or_skip!();
    let me = db.named("moi").await;
    let other = db.named("autre").await;
    let mail = db.su_scalar(&format!("select email from auth.users where id = '{me}'")).await;
    db.su(&format!("update private.forbidden_terms set owners = array[lower('{mail}')] where term in ('lunatix', 'lvnatixx')")).await;
    let set = |id: &uuid::Uuid, name: &str| format!("update public.profiles set username = '{name}' where id = '{id}'");
    for name in ["lunatix", "lvnatixx", "LVNatixx", "lun4tix"] {
        let e = db.x(u(other), &set(&other, name)).await.unwrap_err();
        assert_eq!(sqlstate(&e), "23514", "{name}");
        let r = format!("select public.username_available('{name}') as r");
        assert_eq!(db.q(Who::Anon, &r).await.unwrap()[0]["r"]["reason"], "reserved", "{name}");
        assert_eq!(db.q(u(me), &r).await.unwrap()[0]["r"]["available"], true, "{name}");
    }
    db.x(u(me), &set(&me, "lunatix")).await.unwrap();
    db.x(u(me), &set(&me, "lvnatixx")).await.unwrap();
}

#[tokio::test]
async fn forced_profile_changes_are_cleared_by_the_user_only() {
    let db = db_or_skip!();
    let modo = staff(&db, "modo", "moderator").await;
    let a = db.named("offensant").await;
    db.x(Who::Service, &format!("select public.admin_reset_profile('{modo}', '{a}', array['username','avatar'], true, 'pseudo et photo inappropriés')")).await.unwrap();
    let p = db.q(u(a), "select username, force_username_change, force_avatar_change, avatar_url from public.profiles").await.unwrap();
    assert!(p[0]["username"].as_str().unwrap().starts_with("sona_"));
    assert_eq!(p[0]["force_username_change"], true);
    assert_eq!(p[0]["force_avatar_change"], true);
    // Le client ne peut pas se retirer l'obligation sans changer.
    let e = db.x(u(a), &format!("update public.profiles set force_username_change = false where id = '{a}'")).await.unwrap_err();
    assert_eq!(sqlstate(&e), "42501");
    assert_eq!(db.su_scalar(&format!("select force_username_change from public.profiles where id = '{a}'")).await, "true");
    db.x(u(a), &format!("update public.profiles set username = 'nouveau_pseudo' where id = '{a}'")).await.unwrap();
    assert_eq!(db.su_scalar(&format!("select force_username_change from public.profiles where id = '{a}'")).await, "false");
    assert_eq!(db.su_scalar(&format!("select force_avatar_change from public.profiles where id = '{a}'")).await, "true");
    assert_eq!(db.count(u(a), "select * from public.notifications where kind = 'moderation'").await, 1);
    // Champ inconnu refusé.
    assert!(db.x(Who::Service, &format!("select public.admin_reset_profile('{modo}', '{a}', array['role'], false, 'motif valable')")).await.is_err());
}

#[tokio::test]
async fn secrets_and_internal_columns_never_reach_the_client() {
    let db = db_or_skip!();
    let a = db.named("lastfmeur").await;
    db.su(&format!("insert into public.connected_services (user_id, provider, external_username, secret_encrypted) values ('{a}', 'lastfm', 'lfm_user', 'v1.secret.chiffre')")).await;
    let ok = db.q(u(a), "select provider, external_username from public.connected_services").await.unwrap();
    assert_eq!(ok, json!([{ "provider": "lastfm", "external_username": "lfm_user" }]));
    for sql in ["select secret_encrypted from public.connected_services", "select * from public.connected_services"] {
        assert_eq!(sqlstate(&db.q(u(a), sql).await.unwrap_err()), "42501", "{sql}");
    }
    assert!(db.x(u(a), "update public.connected_services set secret_encrypted = 'x'").await.is_err());
    assert!(db.x(u(a), &format!("insert into public.connected_services (user_id, provider) values ('{a}', 'spotify')")).await.is_err());
    // Déconnecter supprime la clé.
    db.x(u(a), "delete from public.connected_services where provider = 'lastfm'").await.unwrap();
    assert_eq!(db.su_scalar("select count(*) from public.connected_services").await, "0");
    // L'export ne contient jamais de secret.
    db.su(&format!("insert into public.connected_services (user_id, provider, external_username, secret_encrypted) values ('{a}', 'lastfm', 'lfm_user', 'v1.secret.chiffre')")).await;
    let ex = db.q(u(a), "select public.export_my_data()::text as d").await.unwrap();
    assert!(!ex[0]["d"].as_str().unwrap().contains("secret"));
    assert!(ex[0]["d"].as_str().unwrap().contains("lfm_user"));
}

#[tokio::test]
async fn notifications_belong_to_their_owner() {
    let db = db_or_skip!();
    let a = db.named("alice").await;
    let b = db.named("bob").await;
    db.x(u(a), "select public.send_friend_request('bob')").await.unwrap();
    assert!(db.x(u(a), &format!("insert into public.notifications (user_id, kind) values ('{b}', 'warning')")).await.is_err());
    assert_eq!(db.count(u(a), "select * from public.notifications").await, 0);
    assert_eq!(db.x(u(a), "update public.notifications set read_at = now()").await.unwrap(), 0);
    assert_eq!(db.x(u(b), "update public.notifications set read_at = now()").await.unwrap(), 1);
    assert!(db.x(u(b), "update public.notifications set kind = 'warning'").await.is_err());
    // Le serveur musique peut inviter à une session, rien d'autre.
    db.x(Who::Service, &format!("select public.service_notify('{b}', 'session_invite', '{{\"code\":\"ABCD\"}}')")).await.unwrap();
    assert!(db.x(Who::Service, &format!("select public.service_notify('{b}', 'warning', '{{}}')")).await.is_err());
    assert!(db.x(u(a), &format!("select public.service_notify('{b}', 'session_invite', '{{}}')")).await.is_err());
}

#[tokio::test]
async fn relations_for_the_music_server_follow_the_same_rules() {
    let db = db_or_skip!();
    let a = db.named("alice").await;
    let b = db.named("bob").await;
    let c = db.named("carol").await;
    let d = db.named("dave").await;
    db.friends(a, b).await;
    db.privacy(b, "presence_visibility = 'friends'").await;
    db.x(u(a), &format!("select public.block_user('{d}')")).await.unwrap();
    let r = db.q(Who::Service, &format!("select public.batch_relations('{a}', array['{b}','{c}','{d}']::uuid[]) as r")).await.unwrap();
    let r = &r[0]["r"];
    assert_eq!(r[b.to_string()]["friend"], true);
    assert_eq!(r[b.to_string()]["presence"], true);
    assert_eq!(r[c.to_string()]["friend"], false);
    assert_eq!(r[c.to_string()]["presence"], false);
    assert_eq!(r[c.to_string()]["history"], false);
    assert_eq!(r[d.to_string()]["blocked"], true);
    assert_eq!(r[d.to_string()]["profile"], false);
    // Pas appelable depuis un client, et la liste d'amis exclut les sanctionnés.
    assert!(db.q(u(a), &format!("select public.batch_relations('{a}', array['{b}']::uuid[])")).await.is_err());
    assert_eq!(db.q(Who::Service, &format!("select public.service_friend_ids('{a}') as f")).await.unwrap()[0]["f"], json!([b.to_string()]));
    db.su(&format!("update public.profiles set status = 'banned' where id = '{b}'")).await;
    assert_eq!(db.q(Who::Service, &format!("select public.service_friend_ids('{a}') as f")).await.unwrap()[0]["f"], json!([]));
}

#[tokio::test]
async fn guests_have_no_social_existence_until_they_create_an_account() {
    let db = db_or_skip!();
    let guest = db.named("invite_1").await;
    let real = db.named("alice").await;
    db.su(&format!("update auth.users set is_anonymous = true where id = '{guest}'")).await;
    let anon_claims = |id: uuid::Uuid| format!("select set_config('request.jwt.claims', '{{\"sub\":\"{id}\",\"role\":\"authenticated\",\"is_anonymous\":true}}', true)");
    // Un invité ne peut ni inviter, ni signaler, ni utiliser un code d'invitation.
    for sql in [
        "select public.send_friend_request('alice')".to_string(),
        format!("select public.create_report('profile', '{real}', null, 'spam', null)"),
    ] {
        let e = db.x(u(guest), &format!("{}; {sql}", anon_claims(guest))).await.unwrap_err();
        assert_eq!(sqlstate(&e), "42501", "{sql}");
    }
    // Il est invisible des autres, même si on connaît son identifiant ou son pseudo.
    assert_eq!(db.q(u(real), &format!("select public.get_profile('{guest}') as p")).await.unwrap()[0]["p"], json!(null));
    db.x(u(real), "select public.send_friend_request('invite_1')").await.unwrap();
    assert_eq!(db.count(u(guest), "select * from public.list_friend_requests()").await, 0);
    // Il ne voit personne non plus.
    assert!(!db.q(u(guest), &format!("select public.can_i_view('{real}', 'profile_min') as v")).await.unwrap()[0]["v"].as_bool().unwrap());
    // Après création du compte (même identifiant, e-mail ajouté) : tout s'ouvre.
    db.su(&format!("update auth.users set is_anonymous = false, email = 'invite@example.test' where id = '{guest}'")).await;
    db.x(u(real), "select public.send_friend_request('invite_1')").await.unwrap();
    assert_eq!(db.count(u(guest), "select * from public.list_friend_requests()").await, 1);
    assert!(db.q(u(real), &format!("select public.get_profile('{guest}') as p")).await.unwrap()[0]["p"].is_object());
    // Les invités inactifs sont repérés pour suppression.
    let g2 = db.user("x@example.test").await;
    db.su(&format!("update auth.users set is_anonymous = true, created_at = now() - interval '40 days' where id = '{g2}'")).await;
    assert_eq!(db.q(Who::Service, "select public.service_expired_guests(30) as g").await.unwrap()[0]["g"], json!([g2.to_string()]));
}
