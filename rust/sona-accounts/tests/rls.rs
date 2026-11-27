//! Tests SQL / RLS sur un vrai Postgres : confidentialité, amis, blocages,
//! rôles, sanctions, signalements, audit, anti-abus, rétention.

mod common;
use common::{db_message, sqlstate, Who};
use serde_json::json;

fn u(id: uuid::Uuid) -> Who {
    Who::User(id)
}

#[tokio::test]
async fn every_table_has_row_level_security() {
    let db = db_or_skip!();
    let rows = db
        .q(Who::Service, "select schemaname, tablename from pg_tables where schemaname in ('public','private') and not rowsecurity")
        .await
        .unwrap();
    assert_eq!(rows, json!([]), "tables sans RLS");
    let n = db.count(Who::Service, "select 1 from pg_tables where schemaname in ('public','private')").await;
    assert!(n >= 20, "le catalogue est parcouru ({n} tables)");
}

#[tokio::test]
async fn a_new_user_has_a_protective_profile_and_no_friends() {
    let db = db_or_skip!();
    let a = db.user("nouveau@example.test").await;
    let p = db.q(u(a), "select username, role::text, status::text, onboarding_completed from public.profiles").await.unwrap();
    assert_eq!(p[0]["role"], "user");
    assert_eq!(p[0]["status"], "active");
    assert_eq!(p[0]["onboarding_completed"], false);
    assert!(p[0]["username"].as_str().unwrap().starts_with("sona_"));
    let s = db.q(u(a), "select * from public.privacy_settings").await.unwrap();
    assert_eq!(s[0]["profile_visibility"], "minimal");
    assert_eq!(s[0]["presence_visibility"], "nobody", "présence désactivée tant que non activée");
    assert_eq!(s[0]["history_visibility"], "friends");
    assert_eq!(s[0]["stats_visibility"], "friends");
    assert_eq!(s[0]["playlists_visibility"], "friends");
    assert_eq!(db.count(u(a), "select * from public.list_friends()").await, 0);
    assert_eq!(db.count(u(a), "select * from public.friendships").await, 0);
    // Même avec 5 autres comptes, personne n'est ami d'office.
    for i in 0..5 {
        db.user(&format!("autre{i}@example.test")).await;
    }
    assert_eq!(db.count(u(a), "select * from public.list_friends()").await, 0);
}

#[tokio::test]
async fn users_cannot_be_enumerated() {
    let db = db_or_skip!();
    let a = db.named("alice").await;
    let b = db.named("bob_the_builder").await;
    let _c = db.named("carol").await;
    // Un utilisateur ne voit que sa propre ligne.
    assert_eq!(db.q(u(a), "select username from public.profiles").await.unwrap(), json!([{ "username": "alice" }]));
    assert_eq!(db.count(u(a), "select * from public.profiles where username ilike 'b%'").await, 0);
    assert_eq!(db.count(u(a), "select * from public.privacy_settings").await, 1);
    assert_eq!(db.count(u(a), "select * from public.user_settings").await, 1);
    // Un anonyme n'a accès à aucune table.
    let e = db.q(Who::Anon, "select * from public.profiles").await.unwrap_err();
    assert_eq!(sqlstate(&e), "42501");
    // Les tables internes sont fermées, même aux comptes connectés.
    for t in ["private.rate_limits", "private.banned_identifiers", "private.signup_events", "private.forbidden_terms"] {
        let e = db.q(u(a), &format!("select * from {t}")).await.unwrap_err();
        assert_eq!(sqlstate(&e), "42501", "{t}");
    }
    // Aucune recherche : fiche seulement par identifiant exact, jamais d'inconnu.
    assert_eq!(db.q(u(a), &format!("select public.get_profile('{}') as p", uuid::Uuid::new_v4())).await.unwrap()[0]["p"], json!(null));
    // Réponse identique que le pseudo existe ou non.
    let yes = db.q(u(a), "select public.send_friend_request('bob_the_builder') as r").await.unwrap();
    let no = db.q(u(a), "select public.send_friend_request('personne_ici') as r").await.unwrap();
    assert_eq!(yes, no);
    // Le profil de Bob n'est pas lisible par la table, ni son code d'invitation.
    assert_eq!(db.count(u(a), &format!("select * from public.profiles where id = '{b}'")).await, 0);
}

#[tokio::test]
async fn role_and_status_cannot_be_changed_from_the_client() {
    let db = db_or_skip!();
    let a = db.named("mallory").await;
    for sql in [
        format!("update public.profiles set role = 'admin' where id = '{a}'"),
        format!("update public.profiles set status = 'active', status_reason = 'x' where id = '{a}'"),
        format!("update public.profiles set friend_code = 'abc' where id = '{a}'"),
        format!("update public.profiles set created_at = now() - interval '9 years' where id = '{a}'"),
    ] {
        let e = db.x(u(a), &sql).await.unwrap_err();
        assert_eq!(sqlstate(&e), "42501", "{sql}");
    }
    assert_eq!(db.su_scalar(&format!("select role from public.profiles where id = '{a}'")).await, "user");
    // Les fonctions d'administration ne sont pas appelables par un utilisateur…
    let b = db.named("victime").await;
    for sql in [
        format!("select public.admin_sanction('{a}', '{b}', 'ban', 'motif valable')"),
        format!("select public.admin_set_role('{a}', '{a}', 'admin', 'je me promeus')"),
        format!("select public.admin_lift('{a}', '{b}', 'motif valable')"),
        format!("select public.purge_expired()"),
    ] {
        let e = db.x(u(a), &sql).await.unwrap_err();
        assert_eq!(sqlstate(&e), "42501", "{sql}");
        assert!(db.x(Who::Anon, &sql).await.is_err());
    }
    // …et un compte « admin » forgé dans un JWT ne change rien : le rôle vient de la base.
    assert_eq!(db.q(u(a), "select public.is_admin() as a").await.unwrap()[0]["a"], false);
    // On ne modifie pas le profil d'un autre.
    assert_eq!(db.x(u(a), &format!("update public.profiles set bio = 'piraté' where id = '{b}'")).await.unwrap(), 0);
    // Mais on modifie le sien.
    assert_eq!(db.x(u(a), &format!("update public.profiles set bio = 'salut' where id = '{a}'")).await.unwrap(), 1);
}

#[tokio::test]
async fn friend_request_flow() {
    let db = db_or_skip!();
    let a = db.named("alice").await;
    let b = db.named("bob").await;
    db.x(u(a), "select public.send_friend_request('Bob')").await.unwrap();
    // Bob voit la demande reçue, Alice l'envoyée ; rien d'autre.
    let inc = db.q(u(b), "select direction, username from public.list_friend_requests()").await.unwrap();
    assert_eq!(inc, json!([{ "direction": "in", "username": "alice" }]));
    let out = db.q(u(a), "select direction, username from public.list_friend_requests()").await.unwrap();
    assert_eq!(out, json!([{ "direction": "out", "username": "bob" }]));
    assert_eq!(db.count(u(b), "select * from public.notifications where kind = 'friend_request'").await, 1);
    // Les clients ne peuvent pas fabriquer d'amitié.
    let e = db.x(u(a), &format!("insert into public.friendships (requester_id, addressee_id, status) values ('{a}','{b}','accepted')")).await.unwrap_err();
    assert_eq!(sqlstate(&e), "42501");
    assert_eq!(db.x(u(a), &format!("update public.friendships set status='accepted' where requester_id = '{a}'")).await.unwrap_err().to_string().contains("denied"), true);
    // Alice ne peut pas accepter sa propre demande.
    let req: uuid::Uuid = db.su_scalar("select id from public.friendships limit 1").await.parse().unwrap();
    let e = db.x(u(a), &format!("select public.respond_friend_request('{req}', 'accept')")).await.unwrap_err();
    assert_eq!(sqlstate(&e), "P0002");
    // Bob accepte : amis, et Alice est prévenue.
    db.x(u(b), &format!("select public.respond_friend_request('{req}', 'accept')")).await.unwrap();
    assert_eq!(db.q(u(a), "select username from public.list_friends()").await.unwrap(), json!([{ "username": "bob" }]));
    assert_eq!(db.q(u(b), "select username from public.list_friends()").await.unwrap(), json!([{ "username": "alice" }]));
    assert_eq!(db.count(u(a), "select * from public.notifications where kind = 'friend_accepted'").await, 1);
    // Retirer un ami.
    db.x(u(a), &format!("select public.remove_friend('{b}')")).await.unwrap();
    assert_eq!(db.count(u(a), "select * from public.list_friends()").await, 0);
    assert_eq!(db.count(u(b), "select * from public.list_friends()").await, 0);
}

#[tokio::test]
async fn declined_requests_are_silent_and_not_repeatable() {
    let db = db_or_skip!();
    let a = db.named("alice").await;
    let b = db.named("bob").await;
    db.x(u(a), "select public.send_friend_request('bob')").await.unwrap();
    let req: uuid::Uuid = db.su_scalar("select id from public.friendships").await.parse().unwrap();
    db.x(u(b), &format!("select public.respond_friend_request('{req}', 'decline')")).await.unwrap();
    // Aucune notification pour Alice, et sa demande reste « en attente » à l'écran.
    assert_eq!(db.count(u(a), "select * from public.notifications").await, 0);
    assert_eq!(db.q(u(a), "select direction from public.list_friend_requests()").await.unwrap(), json!([{ "direction": "out" }]));
    assert_eq!(db.count(u(b), "select * from public.list_friend_requests()").await, 0);
    // Pas de nouvelle demande pendant 30 jours, sans erreur visible.
    db.x(u(a), "select public.send_friend_request('bob')").await.unwrap();
    assert_eq!(db.count(u(b), "select * from public.list_friend_requests()").await, 0);
    // Après 30 jours, c'est de nouveau possible.
    db.su("update public.friendships set responded_at = now() - interval '31 days'").await;
    db.x(u(a), "select public.send_friend_request('bob')").await.unwrap();
    assert_eq!(db.count(u(b), "select * from public.list_friend_requests()").await, 1);
}

#[tokio::test]
async fn ignoring_hides_a_request_and_crossed_requests_make_friends() {
    let db = db_or_skip!();
    let a = db.named("alice").await;
    let b = db.named("bob").await;
    let c = db.named("carol").await;
    db.x(u(a), "select public.send_friend_request('bob')").await.unwrap();
    let req: uuid::Uuid = db.su_scalar("select id from public.friendships").await.parse().unwrap();
    db.x(u(b), &format!("select public.respond_friend_request('{req}', 'ignore')")).await.unwrap();
    assert_eq!(db.count(u(b), "select * from public.list_friend_requests()").await, 0);
    assert_eq!(db.count(u(a), "select * from public.list_friend_requests()").await, 1, "l'expéditeur ne voit rien de différent");
    // Demandes croisées : Carol → Alice puis Alice → Carol = amies.
    db.x(u(c), "select public.send_friend_request('alice')").await.unwrap();
    db.x(u(a), "select public.send_friend_request('carol')").await.unwrap();
    assert_eq!(db.count(u(a), &format!("select * from public.list_friends() where user_id = '{c}'")).await, 1);
}

#[tokio::test]
async fn invitation_code_and_request_policy() {
    let db = db_or_skip!();
    let a = db.named("alice").await;
    let b = db.named("bob").await;
    let c = db.named("carol").await;
    let code = db.su_scalar(&format!("select friend_code from public.profiles where id = '{b}'")).await;
    // Le code n'est lisible que par son propriétaire.
    assert_eq!(db.count(u(a), &format!("select friend_code from public.profiles where id = '{b}'")).await, 0);
    db.x(u(a), &format!("select public.redeem_friend_code('{code}')")).await.unwrap();
    assert_eq!(db.count(u(b), "select * from public.list_friend_requests() where direction = 'in'").await, 1);
    // Renouveler le code invalide l'ancien.
    let new_code = db.q(u(b), "select public.rotate_friend_code() as c").await.unwrap()[0]["c"].as_str().unwrap().to_string();
    assert_ne!(new_code, code);
    db.x(u(c), &format!("select public.redeem_friend_code('{code}')")).await.unwrap();
    assert_eq!(db.count(u(b), "select * from public.list_friend_requests() where direction = 'in'").await, 1, "ancien code sans effet");
    // « Personne » : ni pseudo ni code n'aboutissent.
    db.privacy(b, "who_can_request = 'nobody'").await;
    db.su("delete from public.friendships").await;
    db.x(u(a), "select public.send_friend_request('bob')").await.unwrap();
    db.x(u(a), &format!("select public.redeem_friend_code('{new_code}')")).await.unwrap();
    assert_eq!(db.count(u(b), "select * from public.list_friend_requests()").await, 0);
    // « Amis d'amis » : il faut un ami commun, sauf par code d'invitation.
    db.privacy(b, "who_can_request = 'friends_of_friends'").await;
    db.x(u(a), "select public.send_friend_request('bob')").await.unwrap();
    assert_eq!(db.count(u(b), "select * from public.list_friend_requests()").await, 0);
    db.friends(a, c).await;
    db.friends(c, b).await;
    db.x(u(a), "select public.send_friend_request('bob')").await.unwrap();
    assert_eq!(db.count(u(b), "select * from public.list_friend_requests()").await, 1);
}

#[tokio::test]
async fn blocking_removes_the_link_and_forbids_everything() {
    let db = db_or_skip!();
    let a = db.named("alice").await;
    let b = db.named("bob").await;
    db.friends(a, b).await;
    db.privacy(a, "presence_visibility = 'everyone', history_visibility = 'everyone', profile_visibility = 'public'").await;
    assert!(db.q(u(b), &format!("select public.can_i_view('{a}', 'presence') as v")).await.unwrap()[0]["v"].as_bool().unwrap());
    db.x(u(a), &format!("select public.block_user('{b}')")).await.unwrap();
    // Plus amis, et le bloqué ne voit rien ni du blocage ni de la personne.
    assert_eq!(db.count(u(a), "select * from public.list_friends()").await, 0);
    assert_eq!(db.count(u(b), "select * from public.list_friends()").await, 0);
    assert_eq!(db.count(u(b), "select * from public.friendships").await, 0, "le bloqué ne voit pas le blocage");
    assert_eq!(db.count(u(a), "select * from public.friendships where status = 'blocked'").await, 1);
    for scope in ["presence", "history", "stats", "playlists", "profile_min", "profile_full"] {
        let v = db.q(u(b), &format!("select public.can_i_view('{a}', '{scope}') as v")).await.unwrap();
        assert_eq!(v[0]["v"], false, "{scope} doit être invisible pour un bloqué");
        let v = db.q(u(a), &format!("select public.can_i_view('{b}', '{scope}') as v")).await.unwrap();
        assert_eq!(v[0]["v"], false, "{scope} : le bloqueur ne voit pas non plus le bloqué");
    }
    assert_eq!(db.q(u(b), &format!("select public.get_profile('{a}') as p")).await.unwrap()[0]["p"], json!(null));
    // Impossible d'envoyer une demande, dans un sens comme dans l'autre.
    db.x(u(b), "select public.send_friend_request('alice')").await.unwrap();
    db.x(u(a), "select public.send_friend_request('bob')").await.unwrap();
    assert_eq!(db.count(u(a), "select * from public.list_friend_requests()").await, 0);
    assert_eq!(db.count(u(b), "select * from public.list_friend_requests()").await, 0);
    let code = db.su_scalar(&format!("select friend_code from public.profiles where id = '{a}'")).await;
    db.x(u(b), &format!("select public.redeem_friend_code('{code}')")).await.unwrap();
    assert_eq!(db.count(u(a), "select * from public.list_friend_requests()").await, 0);
    // Le blocage se lève.
    db.x(u(a), &format!("select public.unblock_user('{b}')")).await.unwrap();
    db.x(u(b), "select public.send_friend_request('alice')").await.unwrap();
    assert_eq!(db.count(u(a), "select * from public.list_friend_requests()").await, 1);
}

#[tokio::test]
async fn a_cannot_read_bs_private_data_without_an_accepted_friendship() {
    let db = db_or_skip!();
    let a = db.named("alice").await;
    let b = db.named("bob").await;
    let view = |who: uuid::Uuid, owner: uuid::Uuid, scope: &'static str| {
        let db = &db;
        async move { db.q(u(who), &format!("select public.can_i_view('{owner}', '{scope}') as v")).await.unwrap()[0]["v"].as_bool().unwrap() }
    };
    // Défauts : seuls pseudo et photo sont visibles d'un inconnu.
    assert!(view(a, b, "profile_min").await);
    for s in ["profile_full", "history", "stats", "playlists", "presence"] {
        assert!(!view(a, b, s).await, "{s} caché à un inconnu");
    }
    // Demande en attente : toujours rien.
    db.x(u(a), "select public.send_friend_request('bob')").await.unwrap();
    assert!(!view(a, b, "history").await);
    // Amis : tout sauf la présence (désactivée tant que non activée).
    db.su("update public.friendships set status = 'accepted'").await;
    for s in ["profile_full", "history", "stats", "playlists"] {
        assert!(view(a, b, s).await, "{s} visible d'un ami");
    }
    assert!(!view(a, b, "presence").await, "présence désactivée par défaut, même pour un ami");
    db.privacy(b, "presence_visibility = 'friends'").await;
    assert!(view(a, b, "presence").await);
    let stranger = db.named("zoe").await;
    assert!(!view(stranger, b, "presence").await);
    db.privacy(b, "presence_visibility = 'everyone'").await;
    assert!(view(stranger, b, "presence").await);
    // Mode invisible : plus de présence pour personne.
    db.privacy(b, "invisible_mode = true").await;
    assert!(!view(a, b, "presence").await && !view(stranger, b, "presence").await);
    assert!(view(b, b, "presence").await, "on se voit soi-même");
    // Réglages séparés.
    db.privacy(b, "history_visibility = 'nobody', stats_visibility = 'everyone'").await;
    assert!(!view(a, b, "history").await);
    assert!(view(stranger, b, "stats").await);
    // Profil privé : personne, pas même un ami ; « amis » : amis seulement.
    db.privacy(b, "profile_visibility = 'private'").await;
    assert!(!view(a, b, "profile_min").await && !view(a, b, "profile_full").await);
    db.privacy(b, "profile_visibility = 'friends'").await;
    assert!(view(a, b, "profile_min").await && !view(stranger, b, "profile_min").await);
    // Données d'un autre via les tables : toujours 0 ligne.
    assert_eq!(db.count(u(stranger), &format!("select * from public.privacy_settings where user_id = '{b}'")).await, 0);
    assert_eq!(db.count(u(stranger), &format!("select * from public.friendships where '{b}' in (requester_id, addressee_id)")).await, 0);
    // La fiche respecte les niveaux.
    db.privacy(b, "profile_visibility = 'minimal'").await;
    let p = db.q(u(stranger), &format!("select public.get_profile('{b}') as p")).await.unwrap();
    let keys: std::collections::BTreeSet<&str> = p[0]["p"].as_object().unwrap().keys().map(|k| k.as_str()).collect();
    assert_eq!(keys, ["avatar_url", "id", "username"].into_iter().collect());
    assert!(p[0]["p"].get("bio").is_none());
    let p = db.q(u(a), &format!("select public.get_profile('{b}') as p")).await.unwrap();
    assert!(p[0]["p"].get("bio").is_some());
}

#[tokio::test]
async fn limits_on_requests_are_enforced() {
    let db = db_or_skip!();
    let a = db.named("spammeur").await;
    for i in 0..6 {
        db.named(&format!("cible{i}")).await;
    }
    // 6 par minute.
    for i in 0..6 {
        db.x(u(a), &format!("select public.send_friend_request('cible{i}')")).await.unwrap();
    }
    let e = db.x(u(a), "select public.send_friend_request('cible0')").await.unwrap_err();
    assert_eq!(sqlstate(&e), "P0001");
    assert_eq!(db_message(&e), "rate_limited");
    // Et un anonyme ne peut rien envoyer du tout.
    assert!(db.x(Who::Anon, "select public.send_friend_request('cible0')").await.is_err());
}

#[tokio::test]
async fn friends_limit_is_enforced() {
    let db = db_or_skip!();
    let a = db.named("populaire").await;
    let b = db.named("nouveau").await;
    db.su(&format!(
        "insert into auth.users (email) select 'f' || g || '@example.test' from generate_series(1, 500) g;
         insert into public.friendships (requester_id, addressee_id, status, responded_at)
           select '{a}', p.id, 'accepted', now() from public.profiles p where p.username like 'sona\\_%' limit 500;"
    ))
    .await;
    assert_eq!(db.su_scalar(&format!("select private.friend_count('{a}')")).await, "500");
    let e = db.x(u(b), "select public.send_friend_request('populaire')").await;
    // La demande n'aboutit pas (le plafond du destinataire est atteint à l'acceptation).
    assert!(e.is_ok());
    let req = db.su_scalar("select id from public.friendships where requester_id = (select id from public.profiles where username='nouveau')").await;
    let e = db.x(u(a), &format!("select public.respond_friend_request('{req}', 'accept')")).await.unwrap_err();
    assert_eq!(db_message(&e), "friends_limit");
}

#[tokio::test]
async fn function_privileges_are_an_exact_allow_list() {
    let db = db_or_skip!();
    let rows = |role: &str, schema: &str| {
        format!(
            "select p.proname::text as f from pg_proc p join pg_namespace n on n.oid = p.pronamespace
             where n.nspname = '{schema}' and has_function_privilege('{role}', p.oid, 'execute') order by 1"
        )
    };
    let names = |v: serde_json::Value| -> Vec<String> { v.as_array().unwrap().iter().map(|r| r["f"].as_str().unwrap().to_string()).collect() };
    let mut expected: Vec<&str> = vec![
        "is_staff", "is_admin", "me_active", "can_i_view", "send_friend_request", "redeem_friend_code", "rotate_friend_code",
        "respond_friend_request", "cancel_friend_request", "remove_friend", "block_user", "unblock_user", "list_friends",
        "list_friend_requests", "list_blocked", "get_profile", "create_report", "create_appeal", "admin_dashboard",
        "admin_list_users", "admin_user_detail", "export_my_data", "username_available",
    ];
    expected.sort();
    let got = names(db.q(Who::Service, &rows("authenticated", "public")).await.unwrap());
    assert_eq!(got, expected, "fonctions ouvertes aux utilisateurs connectés");
    let anon = names(db.q(Who::Service, &rows("anon", "public")).await.unwrap());
    assert_eq!(anon, vec!["username_available"], "fonctions ouvertes aux anonymes");
    // Le schéma interne est fermé : on ne peut même pas en lire le contenu.
    let a = db.named("alice").await;
    for sql in ["select private.effective_status(gen_random_uuid())", "select private.rate_limit('x', 1, interval '1 minute')", "select private.audit(null, 'x', null, null, null, 'x')"] {
        assert_eq!(sqlstate(&db.x(u(a), sql).await.unwrap_err()), "42501", "{sql}");
        assert!(db.x(Who::Anon, sql).await.is_err());
    }
    // Les fonctions « réservées au rôle serveur » ne sont pas exécutables par un client, avant même leur propre garde.
    for sql in [
        format!("select public.service_export('{a}')"), format!("select public.service_friend_ids('{a}')"),
        "select public.purge_expired()".to_string(), "select public.rate_limit_check('k', 1, 1)".to_string(),
    ] {
        assert_eq!(sqlstate(&db.x(u(a), &sql).await.unwrap_err()), "42501", "{sql}");
    }
}

#[tokio::test]
async fn a_user_can_replace_only_their_own_avatar() {
    let db = db_or_skip!();
    let (a, b) = (db.named("alice").await, db.named("bruno").await);
    let upsert = |owner: uuid::Uuid| format!(
        "insert into storage.objects (bucket_id, name) values ('avatars', '{owner}/avatar.webp') \
         on conflict (bucket_id, name) do update set updated_at = now()"
    );
    db.x(u(a), &upsert(a)).await.expect("premier envoi");
    db.x(u(a), &upsert(a)).await.expect("remplacement");
    assert_eq!(sqlstate(&db.x(u(b), &upsert(a)).await.unwrap_err()), "42501");
    assert_eq!(db.count(u(b), "select 1 from storage.objects").await, 0);
}
