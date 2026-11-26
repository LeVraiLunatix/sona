-- Sona : modération, sanctions, signalements, audit, anti-abus.

-- ── Traçabilité : audit_log (non modifiable, non supprimable) ────────────

create table public.audit_log (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  actor_id uuid,
  actor_role text,
  action text not null,
  target_user_id uuid,
  target_type text,
  target_id text,
  reason text,
  details jsonb not null default '{}'::jsonb
);
create index audit_log_at_idx on public.audit_log (at desc);
create index audit_log_target_idx on public.audit_log (target_user_id, at desc);

-- Même pour le service role et le propriétaire : seule la purge de rétention
-- (fonction dédiée, lignes de plus de 12 mois) peut supprimer.
create function private.audit_log_immutable() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE'
     and current_setting('sona.retention_purge', true) = 'on'
     and old.at < now() - interval '12 months' then
    return old;
  end if;
  raise exception 'audit_log_immutable' using errcode = '42501';
end $$;

create trigger audit_log_immutable
  before update or delete on public.audit_log
  for each row execute function private.audit_log_immutable();
create trigger audit_log_no_truncate
  before truncate on public.audit_log
  for each statement execute function private.audit_log_immutable();

create function private.audit(p_actor uuid, p_action text, p_target uuid, p_type text, p_ref text, p_reason text, p_details jsonb default '{}')
returns void language sql security definer set search_path = '' as $$
  insert into public.audit_log (actor_id, actor_role, action, target_user_id, target_type, target_id, reason, details)
  values (p_actor, (select role::text from public.profiles where id = p_actor), p_action, p_target, p_type, p_ref, p_reason, coalesce(p_details, '{}'))
$$;

-- ── Notifications (créées par des fonctions, jamais par le client) ───────

create table public.notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  kind text not null check (kind in ('friend_request', 'friend_accepted', 'session_invite', 'warning', 'report_update', 'moderation', 'appeal_update')),
  payload jsonb not null default '{}'::jsonb,
  read_at timestamptz,
  created_at timestamptz not null default now()
);
create index notifications_user_idx on public.notifications (user_id, created_at desc);

create function private.notify(p_user uuid, p_kind text, p_payload jsonb) returns void
language sql security definer set search_path = '' as $$
  insert into public.notifications (user_id, kind, payload) values (p_user, p_kind, coalesce(p_payload, '{}'))
$$;

-- Pour FastAPI (invitation à une session d'écoute) : service role seulement.
create function public.service_notify(p_user uuid, p_kind text, p_payload jsonb) returns void
language plpgsql security definer set search_path = '' as $$
begin
  perform private.only_service();
  if p_kind not in ('session_invite') then raise exception 'kind_not_allowed'; end if;
  perform private.notify(p_user, p_kind, p_payload);
end $$;

-- ── Alertes pour les admins (envoyées par l'Edge Function `alerts`) ──────

create table public.admin_alerts (
  id uuid primary key default gen_random_uuid(),
  kind text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  sent_at timestamptz
);
create index admin_alerts_created_idx on public.admin_alerts (created_at desc);

create function private.alert(p_kind text, p_payload jsonb) returns void
language sql security definer set search_path = '' as $$
  insert into public.admin_alerts (kind, payload) values (p_kind, coalesce(p_payload, '{}'))
$$;

-- ── Sanctions (historique complet : plusieurs avertissements avant un ban) ─

create type public.sanction_kind as enum ('warning', 'suspension', 'ban', 'quarantine');

create table public.sanctions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  kind public.sanction_kind not null,
  reason text not null check (char_length(btrim(reason)) >= 3 and char_length(reason) <= 1000),
  created_by uuid,            -- null = système (quarantaine automatique)
  created_at timestamptz not null default now(),
  expires_at timestamptz,
  revoked_at timestamptz,
  revoked_by uuid,
  revoke_reason text,
  report_id uuid,
  acknowledged_at timestamptz
);
create index sanctions_user_idx on public.sanctions (user_id, created_at desc);

create table public.appeals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  sanction_id uuid not null references public.sanctions (id) on delete cascade,
  message text not null check (char_length(btrim(message)) between 5 and 1000),
  status text not null default 'open' check (status in ('open', 'accepted', 'rejected')),
  response text,
  handled_by uuid,
  created_at timestamptz not null default now(),
  handled_at timestamptz
);
create unique index appeals_one_open_idx on public.appeals (sanction_id) where status = 'open';
create index appeals_status_idx on public.appeals (status, created_at desc);

-- ── Signalements ─────────────────────────────────────────────────────────

create table public.reports (
  id uuid primary key default gen_random_uuid(),
  reporter_id uuid references public.profiles (id) on delete set null,
  target_type text not null check (target_type in ('profile', 'playlist', 'username', 'avatar', 'session', 'message')),
  target_user_id uuid references public.profiles (id) on delete set null,
  target_ref text check (target_ref is null or char_length(target_ref) <= 200),
  reason text not null check (reason in ('spam', 'harassment', 'inappropriate', 'impersonation', 'other')),
  details text check (details is null or char_length(details) <= 500),
  -- Copie du contenu au moment du signalement (message, pseudo…) : la
  -- preuve reste même si l'auteur le modifie ou le supprime.
  snapshot jsonb not null default '{}'::jsonb check (pg_column_size(snapshot) <= 4096),
  status text not null default 'open' check (status in ('open', 'in_progress', 'resolved', 'dismissed')),
  assigned_to uuid,
  resolution text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  resolved_at timestamptz
);
create index reports_status_idx on public.reports (status, created_at desc);
create index reports_target_idx on public.reports (target_user_id, created_at desc);
create index reports_reporter_idx on public.reports (reporter_id, created_at desc);

create table public.report_notes (
  id uuid primary key default gen_random_uuid(),
  report_id uuid not null references public.reports (id) on delete cascade,
  author_id uuid,
  note text not null check (char_length(btrim(note)) between 1 and 2000),
  created_at timestamptz not null default now()
);
create index report_notes_report_idx on public.report_notes (report_id, created_at);

-- ── Identifiants bannis, domaines jetables, IP ───────────────────────────

create table private.banned_identifiers (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('email', 'oauth', 'email_domain', 'ip')),
  value_hash text,                 -- email / oauth : SHA-256 de la valeur normalisée
  domain text,                     -- email_domain
  cidr cidr,                       -- ip : adresse ou plage
  reason text not null,
  created_by uuid,
  created_at timestamptz not null default now(),
  expires_at timestamptz,
  check ((kind in ('email', 'oauth') and value_hash is not null)
      or (kind = 'email_domain' and domain is not null)
      or (kind = 'ip' and cidr is not null))
);
create index banned_identifiers_hash_idx on private.banned_identifiers (kind, value_hash);

create table private.disposable_domains (
  domain text primary key,
  added_at timestamptz not null default now()
);

create table private.signup_events (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  ip inet,
  email_domain text,
  outcome text not null,
  user_id uuid
);
create index signup_events_at_idx on private.signup_events (at desc);
create index signup_events_ip_idx on private.signup_events (ip, at desc);

-- gmail : points et +alias ignorés ; autres : +alias ignoré.
create function private.norm_email(p_email text) returns text
language plpgsql immutable set search_path = '' as $$
declare
  v_local text := lower(split_part(coalesce(p_email, ''), '@', 1));
  v_domain text := lower(split_part(coalesce(p_email, ''), '@', 2));
begin
  v_local := split_part(v_local, '+', 1);
  if v_domain in ('gmail.com', 'googlemail.com') then
    v_local := replace(v_local, '.', '');
    v_domain := 'gmail.com';
  end if;
  return v_local || '@' || v_domain;
end $$;

create function private.sha(p_text text) returns text
language sql immutable set search_path = '' as $$
  select encode(sha256(convert_to(coalesce(p_text, ''), 'UTF8')), 'hex')
$$;

-- null si l'inscription est acceptée, sinon la raison du refus.
create function private.check_signup(p_email text, p_provider text, p_subject text, p_ip inet) returns text
language plpgsql security definer set search_path = '' as $$
declare
  v_domain text := lower(split_part(coalesce(p_email, ''), '@', 2));
begin
  if p_email is not null and p_email <> '' then
    if exists (select 1 from private.banned_identifiers b
               where b.kind = 'email' and b.value_hash = private.sha(private.norm_email(p_email))
                 and (b.expires_at is null or b.expires_at > now())) then
      return 'banned';
    end if;
    if exists (select 1 from private.banned_identifiers b
               where b.kind = 'email_domain' and b.domain = v_domain
                 and (b.expires_at is null or b.expires_at > now()))
       or exists (select 1 from private.disposable_domains d where d.domain = v_domain) then
      return 'disposable_email';
    end if;
  end if;
  if p_provider is not null and p_subject is not null and p_provider <> 'email'
     and exists (select 1 from private.banned_identifiers b
                 where b.kind = 'oauth' and b.value_hash = private.sha(p_provider || ':' || p_subject)
                   and (b.expires_at is null or b.expires_at > now())) then
    return 'banned';
  end if;
  if p_ip is not null then
    if exists (select 1 from private.banned_identifiers b
               where b.kind = 'ip' and p_ip <<= b.cidr and (b.expires_at is null or b.expires_at > now())) then
      return 'ip_blocked';
    end if;
    -- Création en masse : 5 inscriptions acceptées depuis la même IP en 1 h.
    if (select count(*) from private.signup_events e
        where e.ip = p_ip and e.outcome = 'accepted' and e.at > now() - interval '1 hour') >= 5 then
      return 'ip_burst';
    end if;
  end if;
  return null;
end $$;

-- Dernier rempart, même si le hook HTTP n'est pas branché : e-mail, domaine
-- jetable et identifiant OAuth bannis sont refusés à la création de l'utilisateur.
create function private.auth_users_signup_guard() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_provider text := coalesce(new.raw_app_meta_data ->> 'provider', 'email');
  v_subject text := coalesce(new.raw_user_meta_data ->> 'provider_id', new.raw_user_meta_data ->> 'sub');
  v_reason text;
begin
  v_reason := private.check_signup(new.email, v_provider, v_subject, null);
  if v_reason is not null then
    raise exception 'signup_blocked:%', v_reason using errcode = 'P0001';
  end if;
  return new;
end $$;

create trigger auth_users_signup_guard
  before insert on auth.users
  for each row execute function private.auth_users_signup_guard();

-- Hook « avant création d'utilisateur » (Edge Function `signup-guard`) : seul
-- endroit qui connaît l'adresse IP. Service role seulement.
create function public.signup_guard(p_email text, p_provider text, p_subject text, p_ip inet) returns text
language plpgsql security definer set search_path = '' as $$
declare
  v_reason text;
begin
  perform private.only_service();
  v_reason := private.check_signup(p_email, p_provider, p_subject, p_ip);
  insert into private.signup_events (ip, email_domain, outcome)
  values (p_ip, lower(split_part(coalesce(p_email, ''), '@', 2)), coalesce(v_reason, 'accepted'));
  if v_reason = 'ip_burst' then
    perform private.alert('signup_burst', jsonb_build_object('ip', host(p_ip)));
  end if;
  return v_reason;
end $$;

-- Pic anormal d'inscriptions (planifié, voir 20261126000500_maintenance.sql).
create function private.detect_signup_spike() returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_count int;
begin
  select count(*) into v_count from public.profiles where created_at > now() - interval '1 hour';
  if v_count >= 30 and not exists (select 1 from public.admin_alerts a where a.kind = 'signup_spike' and a.created_at > now() - interval '1 hour') then
    perform private.alert('signup_spike', jsonb_build_object('signups_last_hour', v_count));
  end if;
end $$;

-- ── Actions de modération (service role + acteur vérifié en base) ────────
-- Les Edge Functions authentifient l'appelant (JWT) puis appellent ces
-- fonctions avec son identifiant. La base REVÉRIFIE tout : rôle de l'acteur,
-- hiérarchie, durée maximale, motif obligatoire. Les clients ne peuvent
-- pas les appeler (EXECUTE réservé au service role, voir le fichier RLS).

create function private.require_actor(p_actor uuid, p_min public.user_role) returns public.user_role
language plpgsql security definer set search_path = '' as $$
declare
  v_role public.user_role;
begin
  select role into v_role from public.profiles where id = p_actor;
  if v_role is null or private.effective_status(p_actor) <> 'active' or private.rank(v_role) < private.rank(p_min) then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  return v_role;
end $$;

create function private.require_reason(p_reason text) returns text
language plpgsql immutable set search_path = '' as $$
begin
  if p_reason is null or char_length(btrim(p_reason)) < 3 then
    raise exception 'reason_required' using errcode = '22023';
  end if;
  return btrim(p_reason);
end $$;

-- L'acteur doit être strictement au-dessus de la cible, jamais lui-même.
create function private.require_above(p_actor uuid, p_actor_role public.user_role, p_target uuid) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_target_role public.user_role;
begin
  if p_actor = p_target then raise exception 'cannot_target_self' using errcode = '42501'; end if;
  select role into v_target_role from public.profiles where id = p_target;
  if v_target_role is null then raise exception 'user_not_found' using errcode = 'P0002'; end if;
  if private.rank(p_actor_role) <= private.rank(v_target_role) then
    raise exception 'target_rank_too_high' using errcode = '42501';
  end if;
end $$;

create function private.revoke_sessions(p_user uuid) returns void
language plpgsql security definer set search_path = '' as $$
begin
  delete from auth.sessions where user_id = p_user;
end $$;

-- Garde de second niveau (le vrai rempart est EXECUTE, réservé au rôle serveur) :
-- `role` est le rôle posé par SET ROLE (PostgREST) et reste visible même à
-- l'intérieur d'une fonction SECURITY DEFINER, contrairement à current_user.
create function private.only_service() returns void
language plpgsql set search_path = '' as $$
begin
  if coalesce(current_setting('role', true), 'none') in ('authenticated', 'anon') then
    raise exception 'forbidden' using errcode = '42501';
  end if;
end $$;

-- warning | suspension | ban | quarantine
create function public.admin_sanction(
  p_actor uuid, p_target uuid, p_kind text, p_reason text,
  p_duration interval default null, p_report uuid default null
) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_role public.user_role;
  v_reason text;
  v_kind public.sanction_kind;
  v_until timestamptz;
  v_id uuid;
  v_warnings int;
begin
  perform private.only_service();
  v_reason := private.require_reason(p_reason);
  v_kind := p_kind::public.sanction_kind;
  v_role := private.require_actor(p_actor, (case when v_kind = 'ban' then 'admin' else 'moderator' end)::public.user_role);
  perform private.require_above(p_actor, v_role, p_target);

  if v_kind = 'suspension' then
    if p_duration is null or p_duration <= interval '0' then raise exception 'duration_required' using errcode = '22023'; end if;
    if v_role = 'moderator' and p_duration > interval '7 days' then raise exception 'duration_too_long_for_moderator' using errcode = '42501'; end if;
    v_until := now() + p_duration;
  end if;

  insert into public.sanctions (user_id, kind, reason, created_by, expires_at, report_id)
  values (p_target, v_kind, v_reason, p_actor, v_until, p_report)
  returning id into v_id;

  if v_kind = 'warning' then
    perform private.notify(p_target, 'warning', jsonb_build_object('sanction_id', v_id, 'reason', v_reason));
  else
    update public.profiles
       set status = case v_kind when 'ban' then 'banned' when 'suspension' then 'suspended' else 'quarantined' end::public.account_status,
           status_reason = v_reason, status_until = v_until
     where id = p_target;
    perform private.notify(p_target, 'moderation', jsonb_build_object('sanction_id', v_id, 'kind', v_kind, 'reason', v_reason, 'until', v_until));
  end if;

  if v_kind in ('suspension', 'ban') then
    perform private.revoke_sessions(p_target);
  end if;

  -- Ban : on retient l'e-mail et les identités OAuth (hachés) pour empêcher
  -- de recréer un compte.
  if v_kind = 'ban' then
    insert into private.banned_identifiers (kind, value_hash, reason, created_by)
      select 'email', private.sha(private.norm_email(u.email)), v_reason, p_actor
      from auth.users u where u.id = p_target and u.email is not null;
    insert into private.banned_identifiers (kind, value_hash, reason, created_by)
      select 'oauth', private.sha(i.provider || ':' || i.provider_id), v_reason, p_actor
      from auth.identities i where i.user_id = p_target and i.provider <> 'email';
  end if;

  if p_report is not null then
    update public.reports set status = 'resolved', resolved_at = now(), updated_at = now(),
           resolution = coalesce(resolution, 'sanction:' || v_kind::text)
     where id = p_report and status in ('open', 'in_progress');
  end if;

  perform private.audit(p_actor, 'sanction.' || v_kind::text, p_target, 'user', p_target::text, v_reason,
    jsonb_build_object('sanction_id', v_id, 'until', v_until, 'report_id', p_report));
  select count(*) into v_warnings from public.sanctions where user_id = p_target and kind = 'warning';
  return jsonb_build_object('sanction_id', v_id, 'kind', v_kind, 'until', v_until, 'warnings', v_warnings);
end $$;

-- Lève la suspension, la quarantaine ou le ban en cours.
create function public.admin_lift(p_actor uuid, p_target uuid, p_reason text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_role public.user_role;
  v_reason text := private.require_reason(p_reason);
  v_count int;
  v_has_ban boolean;
begin
  perform private.only_service();
  v_role := private.require_actor(p_actor, 'moderator');
  perform private.require_above(p_actor, v_role, p_target);
  select exists (select 1 from public.sanctions where user_id = p_target and kind = 'ban' and revoked_at is null) into v_has_ban;
  if v_has_ban and v_role <> 'admin' then raise exception 'ban_requires_admin' using errcode = '42501'; end if;

  update public.sanctions set revoked_at = now(), revoked_by = p_actor, revoke_reason = v_reason
   where user_id = p_target and kind in ('suspension', 'ban', 'quarantine') and revoked_at is null;
  get diagnostics v_count = row_count;
  update public.profiles set status = 'active', status_reason = null, status_until = null where id = p_target;
  -- Un ban levé retire aussi les identifiants retenus pour ce compte.
  delete from private.banned_identifiers b
   where b.kind = 'email' and b.value_hash in (select private.sha(private.norm_email(u.email)) from auth.users u where u.id = p_target)
      or b.kind = 'oauth' and b.value_hash in (select private.sha(i.provider || ':' || i.provider_id) from auth.identities i where i.user_id = p_target);
  perform private.notify(p_target, 'moderation', jsonb_build_object('kind', 'lifted'));
  perform private.audit(p_actor, 'sanction.lift', p_target, 'user', p_target::text, v_reason, jsonb_build_object('lifted', v_count));
  return jsonb_build_object('lifted', v_count);
end $$;

-- Réinitialise pseudo / photo / bio, ou impose un changement.
-- p_fields : sous-ensemble de {username, avatar, bio}. p_force : demande à
-- l'utilisateur de choisir lui-même plutôt que d'effacer.
create function public.admin_reset_profile(p_actor uuid, p_target uuid, p_fields text[], p_force boolean, p_reason text) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_role public.user_role;
  v_reason text := private.require_reason(p_reason);
begin
  perform private.only_service();
  v_role := private.require_actor(p_actor, 'moderator');
  perform private.require_above(p_actor, v_role, p_target);
  if exists (select 1 from unnest(p_fields) f where f not in ('username', 'avatar', 'bio')) then
    raise exception 'unknown_field' using errcode = '22023';
  end if;
  perform set_config('sona.bypass_names', 'on', true);
  if 'username' = any (p_fields) then
    update public.profiles set username = 'sona_' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 8),
           force_username_change = p_force where id = p_target;
  end if;
  if 'avatar' = any (p_fields) then
    update public.profiles set avatar_url = null, force_avatar_change = p_force where id = p_target;
  end if;
  if 'bio' = any (p_fields) then
    update public.profiles set bio = null where id = p_target;
  end if;
  perform set_config('sona.bypass_names', 'off', true);
  perform private.notify(p_target, 'moderation', jsonb_build_object('kind', 'profile_reset', 'fields', p_fields, 'reason', v_reason));
  perform private.audit(p_actor, 'profile.reset', p_target, 'user', p_target::text, v_reason,
    jsonb_build_object('fields', p_fields, 'forced', p_force));
end $$;

create function public.admin_set_role(p_actor uuid, p_target uuid, p_role text, p_reason text) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_reason text := private.require_reason(p_reason);
  v_new public.user_role := p_role::public.user_role;
  v_old public.user_role;
begin
  perform private.only_service();
  perform private.require_actor(p_actor, 'admin');
  if p_actor = p_target then raise exception 'cannot_target_self' using errcode = '42501'; end if;
  select role into v_old from public.profiles where id = p_target;
  if v_old is null then raise exception 'user_not_found' using errcode = 'P0002'; end if;
  if v_old = 'admin' and v_new <> 'admin'
     and (select count(*) from public.profiles where role = 'admin' and status = 'active') <= 1 then
    raise exception 'last_admin' using errcode = '42501';
  end if;
  update public.profiles set role = v_new where id = p_target;
  perform private.audit(p_actor, 'role.set', p_target, 'user', p_target::text, v_reason,
    jsonb_build_object('from', v_old, 'to', v_new));
end $$;

-- Journalise une action faite hors base (playlist masquée côté FastAPI, session fermée…).
create function public.admin_audit(p_actor uuid, p_action text, p_target uuid, p_type text, p_ref text, p_reason text, p_details jsonb default '{}') returns void
language plpgsql security definer set search_path = '' as $$
begin
  perform private.only_service();
  perform private.require_actor(p_actor, 'moderator');
  perform private.audit(p_actor, p_action, p_target, p_type, p_ref, private.require_reason(p_reason), p_details);
end $$;

-- Journalise la suppression d'un compte (l'acteur peut être l'utilisateur lui-même).
create function public.log_account_deletion(p_actor uuid, p_target uuid, p_reason text) returns void
language plpgsql security definer set search_path = '' as $$
begin
  perform private.only_service();
  if p_actor is distinct from p_target then
    perform private.require_actor(p_actor, 'admin');
    perform private.require_above(p_actor, private.role_of(p_actor), p_target);
  end if;
  perform private.audit(p_actor, case when p_actor = p_target then 'account.delete_self' else 'account.delete' end,
                        p_target, 'user', p_target::text, private.require_reason(p_reason));
end $$;

create function public.admin_ban_identifier(p_actor uuid, p_kind text, p_value text, p_reason text, p_duration interval default null) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_reason text := private.require_reason(p_reason);
begin
  perform private.only_service();
  perform private.require_actor(p_actor, 'admin');
  if p_kind = 'ip' then
    insert into private.banned_identifiers (kind, cidr, reason, created_by, expires_at)
    values ('ip', p_value::cidr, v_reason, p_actor, case when p_duration is null then null else now() + p_duration end);
  elsif p_kind = 'email_domain' then
    insert into private.banned_identifiers (kind, domain, reason, created_by) values ('email_domain', lower(p_value), v_reason, p_actor);
  elsif p_kind = 'email' then
    insert into private.banned_identifiers (kind, value_hash, reason, created_by) values ('email', private.sha(private.norm_email(p_value)), v_reason, p_actor);
  else
    raise exception 'unknown_kind' using errcode = '22023';
  end if;
  perform private.audit(p_actor, 'identifier.ban', null, 'identifier', p_kind, v_reason, jsonb_build_object('kind', p_kind));
end $$;

create function public.admin_add_forbidden_term(p_actor uuid, p_term text, p_kind text) returns void
language plpgsql security definer set search_path = '' as $$
begin
  perform private.only_service();
  perform private.require_actor(p_actor, 'admin');
  insert into private.forbidden_terms (term, kind) values (private.normalize_name(p_term), p_kind) on conflict do nothing;
  perform private.audit(p_actor, 'forbidden_term.add', null, 'term', p_kind, 'liste de mots interdits', '{}');
end $$;

-- ── Signalements : création (utilisateur) et traitement (équipe) ─────────

create function public.create_report(
  p_target_type text, p_target_user uuid, p_target_ref text, p_reason text, p_details text, p_snapshot jsonb default '{}'
) returns uuid
language plpgsql security definer set search_path = '' as $$
declare
  v_me uuid := auth.uid();
  v_id uuid;
  v_reporters int;
begin
  if v_me is null or not private.is_active(v_me) then raise exception 'forbidden' using errcode = '42501'; end if;
  if p_target_user = v_me then raise exception 'cannot_report_self' using errcode = '22023'; end if;
  -- Doublon récent : on renvoie le même signalement, sans consommer de quota.
  select id into v_id from public.reports
   where reporter_id = v_me and target_type = p_target_type
     and target_user_id is not distinct from p_target_user and target_ref is not distinct from p_target_ref
     and created_at > now() - interval '24 hours' limit 1;
  if v_id is not null then return v_id; end if;
  -- Pas de spam de signalements : 3 / heure, 10 / jour.
  perform private.rate_limit('report_h:' || v_me, 3, interval '1 hour');
  perform private.rate_limit('report_d:' || v_me, 10, interval '1 day');

  insert into public.reports (reporter_id, target_type, target_user_id, target_ref, reason, details, snapshot)
  values (v_me, p_target_type, p_target_user, p_target_ref, p_reason, nullif(btrim(p_details), ''), coalesce(p_snapshot, '{}'))
  returning id into v_id;
  perform private.alert('new_report', jsonb_build_object('report_id', v_id, 'reason', p_reason, 'target_type', p_target_type));

  -- Quarantaine automatique : 5 personnes différentes en 7 jours.
  if p_target_user is not null then
    select count(distinct reporter_id) into v_reporters from public.reports
     where target_user_id = p_target_user and created_at > now() - interval '7 days' and status in ('open', 'in_progress');
    if v_reporters >= 5 and private.role_of(p_target_user) = 'user' and private.effective_status(p_target_user) = 'active' then
      insert into public.sanctions (user_id, kind, reason, created_by)
      values (p_target_user, 'quarantine', 'Mise en quarantaine automatique : ' || v_reporters || ' signalements en 7 jours', null);
      update public.profiles set status = 'quarantined', status_reason = 'Vérification en cours' where id = p_target_user;
      perform private.audit(null, 'sanction.auto_quarantine', p_target_user, 'user', p_target_user::text,
                            v_reporters || ' signalements en 7 jours');
      perform private.alert('auto_quarantine', jsonb_build_object('user_id', p_target_user, 'reports', v_reporters));
    end if;
  end if;
  return v_id;
end $$;

create function public.staff_update_report(p_actor uuid, p_report uuid, p_status text, p_assigned uuid, p_resolution text, p_note text default null) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_reporter uuid;
  v_old text;
begin
  perform private.only_service();
  perform private.require_actor(p_actor, 'moderator');
  if p_status not in ('open', 'in_progress', 'resolved', 'dismissed') then raise exception 'bad_status' using errcode = '22023'; end if;
  select reporter_id, status into v_reporter, v_old from public.reports where id = p_report;
  if not found then raise exception 'report_not_found' using errcode = 'P0002'; end if;
  update public.reports
     set status = p_status, assigned_to = coalesce(p_assigned, assigned_to), resolution = coalesce(p_resolution, resolution),
         updated_at = now(), resolved_at = case when p_status in ('resolved', 'dismissed') then now() else null end
   where id = p_report;
  if p_note is not null and btrim(p_note) <> '' then
    insert into public.report_notes (report_id, author_id, note) values (p_report, p_actor, btrim(p_note));
  end if;
  -- Le signalant est prévenu, sans détail sur la sanction éventuelle.
  if v_reporter is not null and p_status in ('resolved', 'dismissed') and v_old not in ('resolved', 'dismissed') then
    perform private.notify(v_reporter, 'report_update', jsonb_build_object('report_id', p_report, 'status', p_status));
  end if;
  perform private.audit(p_actor, 'report.' || p_status, null, 'report', p_report::text, coalesce(p_resolution, 'traitement du signalement'));
end $$;

-- Contestation d'une sanction : possible même banni (pas de contrôle d'activité).
create function public.create_appeal(p_sanction uuid, p_message text) returns uuid
language plpgsql security definer set search_path = '' as $$
declare
  v_me uuid := auth.uid();
  v_id uuid;
begin
  if v_me is null then raise exception 'forbidden' using errcode = '42501'; end if;
  if not exists (select 1 from public.sanctions where id = p_sanction and user_id = v_me and revoked_at is null and kind <> 'warning') then
    raise exception 'sanction_not_found' using errcode = 'P0002';
  end if;
  perform private.rate_limit('appeal:' || v_me, 3, interval '1 day');
  insert into public.appeals (user_id, sanction_id, message) values (v_me, p_sanction, btrim(p_message)) returning id into v_id;
  perform private.alert('new_appeal', jsonb_build_object('appeal_id', v_id));
  return v_id;
end $$;

create function public.staff_resolve_appeal(p_actor uuid, p_appeal uuid, p_accept boolean, p_response text) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_role public.user_role;
  v_user uuid;
  v_sanction uuid;
  v_response text := private.require_reason(p_response);
begin
  perform private.only_service();
  v_role := private.require_actor(p_actor, 'moderator');
  select user_id, sanction_id into v_user, v_sanction from public.appeals where id = p_appeal and status = 'open';
  if not found then raise exception 'appeal_not_found' using errcode = 'P0002'; end if;
  if p_accept then
    perform public.admin_lift(p_actor, v_user, 'Contestation acceptée : ' || v_response);
  end if;
  update public.appeals set status = case when p_accept then 'accepted' else 'rejected' end,
         response = v_response, handled_by = p_actor, handled_at = now() where id = p_appeal;
  perform private.notify(v_user, 'appeal_update', jsonb_build_object('appeal_id', p_appeal, 'accepted', p_accept, 'response', v_response));
  perform private.audit(p_actor, 'appeal.' || case when p_accept then 'accept' else 'reject' end, v_user, 'appeal', p_appeal::text, v_response);
end $$;

-- ── Lecture pour l'équipe : tableau de bord, liste et fiche d'utilisateur ─

create function public.admin_dashboard() returns jsonb
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.is_staff() then raise exception 'forbidden' using errcode = '42501'; end if;
  return jsonb_build_object(
    'signups_per_day', coalesce((
      select jsonb_agg(jsonb_build_object('day', d.day, 'count', coalesce(c.n, 0)) order by d.day)
      from (select generate_series(current_date - 13, current_date, interval '1 day')::date as day) d
      left join (select created_at::date as day, count(*) n from public.profiles
                 where created_at > current_date - 14 group by 1) c on c.day = d.day), '[]'::jsonb),
    'active_24h', (select count(*) from public.profiles where last_seen_at > now() - interval '24 hours'),
    'active_7d', (select count(*) from public.profiles where last_seen_at > now() - interval '7 days'),
    'total_users', (select count(*) from public.profiles),
    'open_reports', (select count(*) from public.reports where status in ('open', 'in_progress')),
    'open_appeals', (select count(*) from public.appeals where status = 'open'),
    'banned', (select count(*) from public.profiles where status = 'banned'),
    'suspended', (select count(*) from public.profiles where status = 'suspended' and (status_until is null or status_until > now())),
    'quarantined', (select count(*) from public.profiles where status = 'quarantined')
  );
end $$;

create function private.mask_email(p_email text) returns text
language sql immutable set search_path = '' as $$
  select case when p_email is null then null
    else left(split_part(p_email, '@', 1), 1) || '***@' || split_part(p_email, '@', 2) end
$$;

-- Recherche : pseudo, e-mail ou identifiant. Les modérateurs voient l'e-mail masqué.
create function public.admin_list_users(
  p_search text default null, p_role text default null, p_status text default null,
  p_provider text default null, p_since timestamptz default null, p_limit int default 25, p_offset int default 0
) returns table (
  id uuid, username text, email text, avatar_url text, role public.user_role, status public.account_status,
  created_at timestamptz, last_seen_at timestamptz, providers text[], total bigint
)
language plpgsql stable security definer set search_path = '' as $$
declare
  v_admin boolean := public.is_admin();
  v_search text := nullif(btrim(coalesce(p_search, '')), '');
begin
  if not public.is_staff() then raise exception 'forbidden' using errcode = '42501'; end if;
  return query
  with filtered as (
    select p.id, p.username, u.email, p.avatar_url, p.role, p.status, p.created_at, p.last_seen_at,
           coalesce((select array_agg(i.provider order by i.provider) from auth.identities i where i.user_id = p.id), '{}') as providers
    from public.profiles p join auth.users u on u.id = p.id
    where (v_search is null or p.username ilike '%' || replace(replace(v_search, '%', ''), '_', '\_') || '%'
           or u.email ilike '%' || replace(v_search, '%', '') || '%' or p.id::text = v_search)
      and (p_role is null or p.role::text = p_role)
      and (p_status is null or p.status::text = p_status)
      and (p_since is null or p.created_at >= p_since)
      and (p_provider is null or exists (select 1 from auth.identities i where i.user_id = p.id and i.provider = p_provider))
  )
  select f.id, f.username, case when v_admin then f.email else private.mask_email(f.email) end,
         f.avatar_url, f.role, f.status, f.created_at, f.last_seen_at, f.providers, count(*) over ()
  from filtered f order by f.created_at desc
  limit least(greatest(p_limit, 1), 100) offset greatest(p_offset, 0);
end $$;

create function public.admin_user_detail(p_user uuid) returns jsonb
language plpgsql stable security definer set search_path = '' as $$
declare
  v_admin boolean := public.is_admin();
begin
  if not public.is_staff() then raise exception 'forbidden' using errcode = '42501'; end if;
  return (
    select jsonb_build_object(
      'profile', to_jsonb(p) - 'friend_code',
      'email', case when v_admin then u.email else private.mask_email(u.email) end,
      'providers', coalesce((select jsonb_agg(i.provider) from auth.identities i where i.user_id = p.id), '[]'),
      'last_sign_in_at', u.last_sign_in_at,
      'sanctions', coalesce((select jsonb_agg(to_jsonb(s) order by s.created_at desc) from public.sanctions s where s.user_id = p.id), '[]'),
      'reports_received', (select count(*) from public.reports r where r.target_user_id = p.id),
      'reports_made', (select count(*) from public.reports r where r.reporter_id = p.id),
      'friends', (select count(*) from public.friendships f where p.id in (f.requester_id, f.addressee_id) and f.status = 'accepted'),
      'audit', coalesce((select jsonb_agg(to_jsonb(a) order by a.at desc) from
                          (select * from public.audit_log l where l.target_user_id = p.id order by l.at desc limit 20) a), '[]'))
    from public.profiles p join auth.users u on u.id = p.id where p.id = p_user);
end $$;
