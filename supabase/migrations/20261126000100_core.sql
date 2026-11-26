-- Sona : comptes, profils, réglages, confidentialité, services connectés.
--
-- Principes :
--  * `public` = ce que le client voit (via RLS). `private` = tables internes,
--    jamais exposées par PostgREST, accessibles seulement par des fonctions
--    SECURITY DEFINER ou par le service role.
--  * Les colonnes sensibles d'un profil (role, status…) ne sont modifiables
--    ni par colonne (GRANT) ni par déclencheur : seulement par les fonctions
--    d'administration, qui n'acceptent que le service role.
--  * RLS activée sur TOUTES les tables (voir 20261126000400_rls.sql, et le
--    test qui parcourt le catalogue pour le vérifier).

create schema if not exists private;
revoke all on schema private from public;

create type public.user_role as enum ('user', 'moderator', 'admin');
create type public.account_status as enum ('active', 'quarantined', 'suspended', 'banned');

-- ── Profils ──────────────────────────────────────────────────────────────

create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  username text not null,
  display_name text,
  avatar_url text,
  bio text,
  role public.user_role not null default 'user',
  status public.account_status not null default 'active',
  status_reason text,
  status_until timestamptz,
  onboarding_completed boolean not null default false,
  -- Modération : l'utilisateur doit changer de pseudo / de photo avant de continuer.
  force_username_change boolean not null default false,
  force_avatar_change boolean not null default false,
  -- Code personnel (lien d'invitation, QR code). Renouvelable.
  friend_code text not null unique default substr(replace(gen_random_uuid()::text, '-', ''), 1, 14),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_seen_at timestamptz,
  constraint profiles_username_format check (username ~ '^[A-Za-z0-9_.-]{3,20}$'),
  constraint profiles_bio_length check (bio is null or char_length(bio) <= 160),
  constraint profiles_display_name_length check (display_name is null or char_length(display_name) <= 40),
  constraint profiles_avatar_https check (avatar_url is null or (avatar_url ~ '^https://' and char_length(avatar_url) <= 500))
);
create unique index profiles_username_lower_idx on public.profiles (lower(username));
create index profiles_role_idx on public.profiles (role) where role <> 'user';
create index profiles_status_idx on public.profiles (status) where status <> 'active';
create index profiles_created_idx on public.profiles (created_at desc);

-- Statut réel : une suspension dont la date est passée ne compte plus.
create function private.effective_status(p_user uuid) returns public.account_status
language sql stable security definer set search_path = '' as $$
  select case
           when p.status = 'suspended' and p.status_until is not null and p.status_until <= now() then 'active'::public.account_status
           else p.status
         end
  from public.profiles p where p.id = p_user
$$;

-- Compte utilisable : actif ou en quarantaine (dans ce cas il reste invisible
-- des autres et ne peut rien envoyer, voir les fonctions sociales).
create function private.is_active(p_user uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select coalesce(private.effective_status(p_user) in ('active', 'quarantined'), false)
$$;

create function private.role_of(p_user uuid) returns public.user_role
language sql stable security definer set search_path = '' as $$
  select role from public.profiles where id = p_user
$$;

create function private.rank(p_role public.user_role) returns int
language sql immutable set search_path = '' as $$
  select case p_role when 'admin' then 3 when 'moderator' then 2 else 1 end
$$;

create function public.is_staff() returns boolean
language sql stable security definer set search_path = '' as $$
  select coalesce(private.effective_status(auth.uid()) = 'active'
                  and private.role_of(auth.uid()) in ('moderator', 'admin'), false)
$$;

create function public.is_admin() returns boolean
language sql stable security definer set search_path = '' as $$
  select coalesce(private.effective_status(auth.uid()) = 'active'
                  and private.role_of(auth.uid()) = 'admin', false)
$$;

-- ── Anti-abus : limites par clé (fenêtre fixe) ────────────────────────────

create table private.rate_limits (
  key text not null,
  window_start timestamptz not null,
  hits int not null default 0,
  primary key (key, window_start)
);

create function private.rate_limit(p_key text, p_max int, p_window interval) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_start timestamptz := to_timestamp(floor(extract(epoch from now()) / extract(epoch from p_window)) * extract(epoch from p_window));
  v_hits int;
begin
  insert into private.rate_limits as r (key, window_start, hits) values (p_key, v_start, 1)
  on conflict (key, window_start) do update set hits = r.hits + 1
  returning r.hits into v_hits;
  if v_hits > p_max then
    raise exception 'rate_limited' using errcode = 'P0001', hint = 'Trop de requêtes, réessaie plus tard.';
  end if;
end $$;

-- Pour les Edge Functions (service role) : même compteur.
create function public.rate_limit_check(p_key text, p_max int, p_window_seconds int) returns boolean
language plpgsql security definer set search_path = '' as $$
begin
  perform private.rate_limit(p_key, p_max, make_interval(secs => p_window_seconds));
  return true;
exception when sqlstate 'P0001' then
  return false;
end $$;

-- ── Pseudos : format, réservés, mots interdits ────────────────────────────

create table private.forbidden_terms (
  term text primary key,
  kind text not null check (kind in ('reserved', 'offensive')),
  added_at timestamptz not null default now()
);

-- minuscules, sans accents, « leet speak » défait, séparateurs retirés.
create function private.normalize_name(p_text text) returns text
language sql immutable set search_path = '' as $$
  select regexp_replace(
    translate(lower(coalesce(p_text, '')),
      'àâäáãåçéèêëíìîïñóòôöõúùûüýÿ0134578@$!|',
      'aaaaaaceeeeiiiinooooouuuuyyoieastbasii'),
    '[^a-z0-9]', '', 'g')
$$;

-- null si le texte est accepté, sinon la raison.
create function private.name_problem(p_text text) returns text
language plpgsql stable security definer set search_path = '' as $$
declare
  n text := private.normalize_name(p_text);
begin
  if p_text is null or p_text !~ '^[A-Za-z0-9_.-]{3,20}$' then return 'format'; end if;
  if exists (select 1 from private.forbidden_terms t where t.kind = 'reserved' and t.term = n) then return 'reserved'; end if;
  if exists (select 1 from private.forbidden_terms t where t.kind = 'offensive' and position(t.term in n) > 0) then return 'offensive'; end if;
  return null;
end $$;

-- Texte libre (chat, bio) : seulement les mots offensants.
create function private.text_has_offensive(p_text text) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from private.forbidden_terms t
    where t.kind = 'offensive' and position(t.term in private.normalize_name(p_text)) > 0)
$$;

-- Disponibilité en direct (écran d'inscription). Limitée : 40 appels / minute.
create function public.username_available(p_name text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_problem text;
begin
  perform private.rate_limit('username_check:' || coalesce(auth.uid()::text, 'anon'), 40, interval '1 minute');
  v_problem := private.name_problem(p_name);
  if v_problem is not null then
    return jsonb_build_object('available', false, 'reason', v_problem);
  end if;
  if exists (select 1 from public.profiles p where lower(p.username) = lower(p_name) and p.id is distinct from auth.uid()) then
    return jsonb_build_object('available', false, 'reason', 'taken');
  end if;
  return jsonb_build_object('available', true);
end $$;

create function private.profiles_username_guard() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_problem text;
begin
  if current_setting('sona.bypass_names', true) = 'on' then return new; end if;
  v_problem := private.name_problem(new.username);
  if v_problem is not null then
    raise exception 'username_%', v_problem using errcode = '23514';
  end if;
  return new;
end $$;

create trigger profiles_username_guard
  before insert or update of username on public.profiles
  for each row execute function private.profiles_username_guard();

-- Le rôle, le statut… ne bougent JAMAIS depuis le client (en plus des GRANT
-- par colonne) : un UPDATE d'un de ces champs sous `authenticated` échoue.
create function private.profiles_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if current_user in ('authenticated', 'anon') then
    if new.id is distinct from old.id
       or new.role is distinct from old.role
       or new.status is distinct from old.status
       or new.status_reason is distinct from old.status_reason
       or new.status_until is distinct from old.status_until
       or new.friend_code is distinct from old.friend_code
       or new.created_at is distinct from old.created_at
       or new.last_seen_at is distinct from old.last_seen_at then
      raise exception 'protected_column' using errcode = '42501';
    end if;
    -- Changer de pseudo / de photo lève l'obligation correspondante.
    new.force_username_change := case when new.username is distinct from old.username then false else old.force_username_change end;
    new.force_avatar_change := case when new.avatar_url is distinct from old.avatar_url then false else old.force_avatar_change end;
  end if;
  new.updated_at := now();
  return new;
end $$;

create trigger profiles_guard
  before update on public.profiles
  for each row execute function private.profiles_guard();

-- ── Réglages de l'app ────────────────────────────────────────────────────

create table public.user_settings (
  user_id uuid primary key references public.profiles (id) on delete cascade,
  theme text not null default 'system' check (theme in ('system', 'dark', 'light')),
  audio_quality text not null default 'best' check (char_length(audio_quality) <= 20),
  car_mode_auto boolean not null default false,
  scrobbling_enabled boolean not null default true,
  extra jsonb not null default '{}'::jsonb check (pg_column_size(extra) <= 4096),
  updated_at timestamptz not null default now()
);

-- ── Confidentialité : valeurs les plus protectrices par défaut ───────────

create table public.privacy_settings (
  user_id uuid primary key references public.profiles (id) on delete cascade,
  -- public : tout le monde voit tout ; minimal : pseudo + photo pour tous,
  -- le reste pour les amis ; friends : amis seulement ; private : personne.
  profile_visibility text not null default 'minimal' check (profile_visibility in ('public', 'minimal', 'friends', 'private')),
  who_can_request text not null default 'everyone' check (who_can_request in ('everyone', 'friends_of_friends', 'nobody')),
  presence_visibility text not null default 'nobody' check (presence_visibility in ('everyone', 'friends', 'nobody')),
  history_visibility text not null default 'friends' check (history_visibility in ('everyone', 'friends', 'nobody')),
  stats_visibility text not null default 'friends' check (stats_visibility in ('everyone', 'friends', 'nobody')),
  playlists_visibility text not null default 'friends' check (playlists_visibility in ('everyone', 'friends', 'nobody')),
  -- J'écoute sans apparaître nulle part.
  invisible_mode boolean not null default false,
  do_not_disturb boolean not null default false,
  updated_at timestamptz not null default now()
);

-- ── Services connectés (Last.fm…) ────────────────────────────────────────

create table public.connected_services (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  provider text not null check (provider in ('lastfm', 'spotify', 'deezer')),
  external_username text,
  -- Clé de session chiffrée (AES-GCM) par l'Edge Function. Jamais lisible
  -- côté client : voir les GRANT par colonne.
  secret_encrypted text,
  connected_at timestamptz not null default now(),
  last_sync_at timestamptz,
  last_error text,
  unique (user_id, provider)
);

-- ── Passkeys (WebAuthn) ──────────────────────────────────────────────────

create table public.passkey_credentials (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  credential_id text not null unique,
  public_key text not null,
  counter bigint not null default 0,
  transports text[],
  device_name text,
  created_at timestamptz not null default now(),
  last_used_at timestamptz
);
create index passkey_credentials_user_idx on public.passkey_credentials (user_id);

create table private.passkey_challenges (
  id uuid primary key default gen_random_uuid(),
  user_id uuid,
  email text,
  challenge text not null,
  kind text not null check (kind in ('register', 'login')),
  expires_at timestamptz not null default now() + interval '5 minutes'
);

-- ── Création du compte ───────────────────────────────────────────────────

-- Un profil, des réglages et une confidentialité protectrice à chaque inscription.
create function private.handle_new_user() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_name text := 'sona_' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 8);
  v_avatar text := coalesce(new.raw_user_meta_data ->> 'avatar_url', new.raw_user_meta_data ->> 'picture');
begin
  perform set_config('sona.bypass_names', 'on', true);
  if v_avatar is null or v_avatar !~ '^https://' or char_length(v_avatar) > 500 then v_avatar := null; end if;
  insert into public.profiles (id, username, avatar_url) values (new.id, v_name, v_avatar);
  perform set_config('sona.bypass_names', 'off', true);
  insert into public.user_settings (user_id) values (new.id);
  insert into public.privacy_settings (user_id) values (new.id);
  return new;
end $$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function private.handle_new_user();
