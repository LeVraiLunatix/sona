-- Sona : droits d'exécution des fonctions. DERNIÈRE migration : repart de zéro et ouvre à la main.
--
-- Postgres accorde EXECUTE à PUBLIC sur toute nouvelle fonction ; un simple REVOKE « par défaut » ne
-- retire pas ce droit implicite. On retire donc tout ici, après la création de toutes les fonctions, puis
-- on n'ouvre que la liste ci-dessous. Un test (`function_privileges_are_an_exact_allow_list`) compare cette
-- liste au catalogue : toute fonction ajoutée plus tard doit être ajoutée ici, sinon elle reste fermée.
-- En plus : les fonctions d'administration vérifient elles-mêmes qu'elles sont appelées par le rôle serveur.

revoke all on all functions in schema public from public, anon, authenticated;
revoke all on all functions in schema private from public, anon, authenticated;

grant execute on function
  public.is_staff(), public.is_admin(), public.me_active(),
  public.can_i_view(uuid, text),
  public.send_friend_request(text), public.redeem_friend_code(text), public.rotate_friend_code(),
  public.respond_friend_request(uuid, text), public.cancel_friend_request(uuid),
  public.remove_friend(uuid), public.block_user(uuid), public.unblock_user(uuid),
  public.list_friends(), public.list_friend_requests(), public.list_blocked(), public.get_profile(uuid),
  public.create_report(text, uuid, text, text, text, jsonb), public.create_appeal(uuid, text),
  public.admin_dashboard(), public.admin_list_users(text, text, text, text, timestamptz, int, int),
  public.admin_user_detail(uuid), public.export_my_data()
  to authenticated;

-- Disponibilité d'un pseudo : aussi pour qui n'a pas encore de compte (inscription).
grant execute on function public.username_available(text) to anon, authenticated;

-- Rôle serveur (PostgREST service_role ; sona-accounts se connecte en `postgres`).
grant execute on all functions in schema public to service_role;
