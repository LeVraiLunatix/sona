-- Sona : RLS sur TOUTES les tables, droits explicites.
--
-- Politique : tout est refusé, on ouvre à la main. Aucun client ne peut
-- écrire dans friendships, sanctions, reports, audit_log, notifications…
-- (créés par des fonctions SECURITY DEFINER qui revérifient tout).
-- Les écritures d'administration passent par `sona-accounts` (rôle serveur).

-- ── RLS partout, aussi sur le schéma interne ─────────────────────────────

do $$
declare
  t record;
begin
  for t in select schemaname, tablename from pg_tables where schemaname in ('public', 'private') loop
    execute format('alter table %I.%I enable row level security', t.schemaname, t.tablename);
  end loop;
end $$;

-- ── Droits : on part de zéro ─────────────────────────────────────────────

revoke all on all tables in schema public from anon, authenticated;
revoke all on all tables in schema private from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke all on all functions in schema public from public, anon, authenticated;
revoke all on all functions in schema private from public, anon, authenticated;
revoke usage on schema private from anon, authenticated;

-- Les fonctions créées plus tard ne sont pas ouvertes d'office.
alter default privileges in schema public revoke execute on functions from public, anon, authenticated;
alter default privileges in schema private revoke execute on functions from public, anon, authenticated;

-- ── Fonctions appelables par un utilisateur connecté ─────────────────────

create function public.me_active() returns boolean
language sql stable security definer set search_path = '' as $$
  select coalesce(private.is_active(auth.uid()), false)
$$;

grant execute on function
  public.is_staff(), public.is_admin(), public.me_active(),
  public.can_i_view(uuid, text),
  public.send_friend_request(text), public.redeem_friend_code(text), public.rotate_friend_code(),
  public.respond_friend_request(uuid, text), public.cancel_friend_request(uuid),
  public.remove_friend(uuid), public.block_user(uuid), public.unblock_user(uuid),
  public.list_friends(), public.list_friend_requests(), public.list_blocked(), public.get_profile(uuid),
  public.create_report(text, uuid, text, text, text, jsonb), public.create_appeal(uuid, text),
  public.admin_dashboard(), public.admin_list_users(text, text, text, text, timestamptz, int, int),
  public.admin_user_detail(uuid)
  to authenticated;

-- Disponibilité d'un pseudo : aussi pour qui n'a pas encore de compte (inscription).
grant execute on function public.username_available(text) to anon, authenticated;

-- ── Profils ──────────────────────────────────────────────────────────────

create policy profiles_select on public.profiles for select to authenticated
  using (id = auth.uid() or public.is_staff());
create policy profiles_update on public.profiles for update to authenticated
  using (id = auth.uid() and public.me_active()) with check (id = auth.uid() and public.me_active());

grant select on public.profiles to authenticated;
grant update (username, display_name, avatar_url, bio, onboarding_completed) on public.profiles to authenticated;

-- ── Réglages et confidentialité ──────────────────────────────────────────

create policy user_settings_select on public.user_settings for select to authenticated using (user_id = auth.uid());
create policy user_settings_update on public.user_settings for update to authenticated
  using (user_id = auth.uid() and public.me_active()) with check (user_id = auth.uid() and public.me_active());
grant select, update (theme, audio_quality, car_mode_auto, scrobbling_enabled, extra) on public.user_settings to authenticated;

create policy privacy_select on public.privacy_settings for select to authenticated using (user_id = auth.uid());
create policy privacy_update on public.privacy_settings for update to authenticated
  using (user_id = auth.uid() and public.me_active()) with check (user_id = auth.uid() and public.me_active());
grant select, update (profile_visibility, who_can_request, presence_visibility, history_visibility, stats_visibility,
                      playlists_visibility, invisible_mode, do_not_disturb) on public.privacy_settings to authenticated;

-- ── Services connectés : la clé chiffrée n'est jamais lisible par le client ─

create policy connected_services_select on public.connected_services for select to authenticated using (user_id = auth.uid());
create policy connected_services_delete on public.connected_services for delete to authenticated
  using (user_id = auth.uid() and public.me_active());
grant select (id, user_id, provider, external_username, connected_at, last_sync_at, last_error) on public.connected_services to authenticated;
grant delete on public.connected_services to authenticated;

-- ── Passkeys ─────────────────────────────────────────────────────────────

create policy passkeys_select on public.passkey_credentials for select to authenticated using (user_id = auth.uid());
create policy passkeys_delete on public.passkey_credentials for delete to authenticated
  using (user_id = auth.uid() and public.me_active());
grant select (id, user_id, device_name, created_at, last_used_at) on public.passkey_credentials to authenticated;
grant delete on public.passkey_credentials to authenticated;

-- ── Notifications ────────────────────────────────────────────────────────

create policy notifications_select on public.notifications for select to authenticated using (user_id = auth.uid());
create policy notifications_update on public.notifications for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy notifications_delete on public.notifications for delete to authenticated using (user_id = auth.uid());
grant select, delete on public.notifications to authenticated;
grant update (read_at) on public.notifications to authenticated;

-- ── Amitiés : lecture limitée à mes lignes, aucune écriture directe ──────
-- Une demande refusée est invisible de l'expéditeur ; un blocage, de la personne bloquée.

create policy friendships_select on public.friendships for select to authenticated
  using ((requester_id = auth.uid() and status in ('pending', 'accepted', 'blocked'))
      or (addressee_id = auth.uid() and status in ('pending', 'accepted')));
grant select on public.friendships to authenticated;

-- ── Sanctions, contestations : visibles de la personne concernée, même bannie ─

create policy sanctions_select on public.sanctions for select to authenticated
  using (user_id = auth.uid() or public.is_staff());
create policy sanctions_ack on public.sanctions for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
grant select on public.sanctions to authenticated;
grant update (acknowledged_at) on public.sanctions to authenticated;

create policy appeals_select on public.appeals for select to authenticated
  using (user_id = auth.uid() or public.is_staff());
grant select on public.appeals to authenticated;

-- ── Signalements : le signalant voit les siens, l'équipe voit tout ───────

create policy reports_select on public.reports for select to authenticated
  using (reporter_id = auth.uid() or public.is_staff());
grant select on public.reports to authenticated;

create policy report_notes_select on public.report_notes for select to authenticated using (public.is_staff());
grant select on public.report_notes to authenticated;

-- ── Journal d'audit et alertes : admins (journal) / équipe (alertes) ─────

create policy audit_log_select on public.audit_log for select to authenticated using (public.is_admin());
grant select on public.audit_log to authenticated;

create policy admin_alerts_select on public.admin_alerts for select to authenticated using (public.is_staff());
grant select on public.admin_alerts to authenticated;

-- ── Le rôle serveur (sona-accounts, PostgREST service_role) ──────────────

grant all on all tables in schema public to service_role;
grant execute on all functions in schema public to service_role;
