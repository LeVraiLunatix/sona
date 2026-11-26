-- Sona : amis, blocages, visibilité.
--
-- Fini le « tout le monde est ami » : personne n'est ami avec personne par
-- défaut. Une amitié est une ligne `friendships` ; toute écriture passe par
-- une fonction (jamais d'INSERT / UPDATE direct, voir RLS) ; aucune liste
-- publique d'utilisateurs, aucune recherche par préfixe.

create type public.friendship_status as enum ('pending', 'accepted', 'declined', 'blocked');

create table public.friendships (
  id uuid primary key default gen_random_uuid(),
  -- pending / declined : qui a envoyé la demande. blocked : qui bloque.
  requester_id uuid not null references public.profiles (id) on delete cascade,
  addressee_id uuid not null references public.profiles (id) on delete cascade,
  status public.friendship_status not null default 'pending',
  -- « Ignorer » : la demande disparaît de ma liste sans être refusée.
  ignored boolean not null default false,
  created_at timestamptz not null default now(),
  responded_at timestamptz,
  check (requester_id <> addressee_id)
);
-- Une seule ligne par paire, quel que soit le sens.
create unique index friendships_pair_idx
  on public.friendships (least(requester_id, addressee_id), greatest(requester_id, addressee_id));
create index friendships_requester_idx on public.friendships (requester_id, status);
create index friendships_addressee_idx on public.friendships (addressee_id, status);

-- Limites « raisonnables » (modifiables ici, en un seul endroit).
create function private.max_friends() returns int language sql immutable set search_path = '' as $$ select 500 $$;
create function private.max_requests_per_day() returns int language sql immutable set search_path = '' as $$ select 20 $$;
create function private.max_pending_incoming() returns int language sql immutable set search_path = '' as $$ select 100 $$;

-- ── Relations ────────────────────────────────────────────────────────────

create function private.are_friends(a uuid, b uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.friendships f
    where f.status = 'accepted'
      and ((f.requester_id = a and f.addressee_id = b) or (f.requester_id = b and f.addressee_id = a)))
$$;

create function private.is_blocked_between(a uuid, b uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.friendships f
    where f.status = 'blocked'
      and ((f.requester_id = a and f.addressee_id = b) or (f.requester_id = b and f.addressee_id = a)))
$$;

create function private.common_friend(a uuid, b uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1
    from public.friendships fa
    join public.friendships fb
      on case when fa.requester_id = a then fa.addressee_id else fa.requester_id end
       = case when fb.requester_id = b then fb.addressee_id else fb.requester_id end
    where fa.status = 'accepted' and a in (fa.requester_id, fa.addressee_id)
      and fb.status = 'accepted' and b in (fb.requester_id, fb.addressee_id))
$$;

create function private.friend_count(p_user uuid) returns int
language sql stable security definer set search_path = '' as $$
  select count(*)::int from public.friendships f
  where f.status = 'accepted' and p_user in (f.requester_id, f.addressee_id)
$$;

-- Visible des autres : compte actif (ni suspendu, ni banni, ni en quarantaine).
create function private.is_visible(p_user uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select coalesce(private.effective_status(p_user) = 'active', false)
$$;

-- LA règle de visibilité, appliquée côté serveur (SQL, et FastAPI via
-- batch_relations). scope : profile_min | profile_full | presence | history
-- | stats | playlists.
create function private.can_view(p_viewer uuid, p_owner uuid, p_scope text) returns boolean
language plpgsql stable security definer set search_path = '' as $$
declare
  s public.privacy_settings;
  v_level text;
  v_friend boolean;
begin
  if p_viewer is null or p_owner is null then return false; end if;
  if p_viewer = p_owner then return private.is_active(p_owner); end if;
  if not private.is_active(p_viewer) or not private.is_visible(p_owner) then return false; end if;
  if private.is_blocked_between(p_viewer, p_owner) then return false; end if;
  select * into s from public.privacy_settings where user_id = p_owner;
  if not found then return false; end if;
  v_friend := private.are_friends(p_viewer, p_owner);

  if p_scope = 'profile_min' then
    return case s.profile_visibility when 'public' then true when 'minimal' then true else v_friend and s.profile_visibility = 'friends' end;
  elsif p_scope = 'profile_full' then
    return case s.profile_visibility when 'public' then true when 'private' then false else v_friend end;
  end if;

  -- « J'écoute sans apparaître » : plus rien de ce qui se passe en direct.
  if p_scope = 'presence' and s.invisible_mode then return false; end if;
  v_level := case p_scope
    when 'presence' then s.presence_visibility
    when 'history' then s.history_visibility
    when 'stats' then s.stats_visibility
    when 'playlists' then s.playlists_visibility
    else 'nobody' end;
  return case v_level when 'everyone' then true when 'friends' then v_friend else false end;
end $$;

-- Pour le client : « puis-je voir X chez cette personne ? ».
create function public.can_i_view(p_owner uuid, p_scope text) returns boolean
language sql stable security definer set search_path = '' as $$
  select private.can_view(auth.uid(), p_owner, p_scope)
$$;

-- Pour FastAPI (service role) : tout ce qu'il faut savoir sur la relation
-- entre `p_viewer` et chacun des `p_others`, en un seul appel.
create function public.batch_relations(p_viewer uuid, p_others uuid[]) returns jsonb
language plpgsql stable security definer set search_path = '' as $$
begin
  perform private.only_service();
  return coalesce((
    select jsonb_object_agg(o::text, jsonb_build_object(
      'friend', private.are_friends(p_viewer, o),
      'blocked', private.is_blocked_between(p_viewer, o),
      'visible', private.is_visible(o),
      'presence', private.can_view(p_viewer, o, 'presence'),
      'history', private.can_view(p_viewer, o, 'history'),
      'stats', private.can_view(p_viewer, o, 'stats'),
      'playlists', private.can_view(p_viewer, o, 'playlists'),
      'profile', private.can_view(p_viewer, o, 'profile_min')))
    from unnest(p_others) o), '{}'::jsonb);
end $$;

-- Mes amis acceptés (visibles), pour FastAPI et le client.
create function public.service_friend_ids(p_user uuid) returns uuid[]
language plpgsql stable security definer set search_path = '' as $$
begin
  perform private.only_service();
  return coalesce((
    select array_agg(case when f.requester_id = p_user then f.addressee_id else f.requester_id end)
    from public.friendships f
    where f.status = 'accepted' and p_user in (f.requester_id, f.addressee_id)
      and private.is_visible(case when f.requester_id = p_user then f.addressee_id else f.requester_id end)
      and private.is_active(p_user)), '{}');
end $$;

-- Identité minimale d'un compte (pseudo + photo) pour FastAPI, sans vérifier de lien.
create function public.service_profiles(p_users uuid[]) returns table (id uuid, username text, display_name text, avatar_url text, role public.user_role, status public.account_status, status_reason text, status_until timestamptz, onboarding_completed boolean)
language plpgsql stable security definer set search_path = '' as $$
begin
  perform private.only_service();
  return query select p.id, p.username, p.display_name, p.avatar_url, p.role,
                      private.effective_status(p.id), p.status_reason, p.status_until, p.onboarding_completed
               from public.profiles p where p.id = any (p_users);
end $$;

create function public.service_touch(p_user uuid) returns void
language plpgsql security definer set search_path = '' as $$
begin
  perform private.only_service();
  update public.profiles set last_seen_at = now() where id = p_user and (last_seen_at is null or last_seen_at < now() - interval '5 minutes');
end $$;

-- ── Demandes d'amis ──────────────────────────────────────────────────────

-- Cœur commun de « par pseudo » et « par code d'invitation ». Réponse
-- identique que la personne existe ou non, accepte ou non : aucune énumération.
create function private.request_friend(p_me uuid, p_target uuid, p_via_code boolean) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_row public.friendships;
  v_setting text;
  v_existing boolean;
begin
  if p_target is null or p_target = p_me then return; end if;
  if not private.is_visible(p_target) then return; end if;
  if private.is_blocked_between(p_me, p_target) then return; end if;

  select * into v_row from public.friendships f
   where least(f.requester_id, f.addressee_id) = least(p_me, p_target)
     and greatest(f.requester_id, f.addressee_id) = greatest(p_me, p_target);
  v_existing := found;

  if v_existing then
    if v_row.status = 'accepted' then return; end if;
    -- Il m'avait déjà invité : demande croisée = acceptation.
    if v_row.status = 'pending' and v_row.requester_id = p_target then
      if private.friend_count(p_me) >= private.max_friends() or private.friend_count(p_target) >= private.max_friends() then return; end if;
      update public.friendships set status = 'accepted', ignored = false, responded_at = now() where id = v_row.id;
      perform private.notify(p_target, 'friend_accepted', jsonb_build_object('user_id', p_me));
      return;
    end if;
    if v_row.status = 'pending' then return; end if;
    -- Refusée : pas de nouvelle demande pendant 30 jours (sans rien dire).
    if v_row.status = 'declined' and v_row.responded_at > now() - interval '30 days' then return; end if;
  end if;

  select who_can_request into v_setting from public.privacy_settings where user_id = p_target;
  if v_setting = 'nobody' then return; end if;
  if v_setting = 'friends_of_friends' and not p_via_code and not private.common_friend(p_me, p_target) then return; end if;
  if private.friend_count(p_me) >= private.max_friends() then raise exception 'friends_limit' using errcode = 'P0001'; end if;
  if (select count(*) from public.friendships f where f.addressee_id = p_target and f.status = 'pending') >= private.max_pending_incoming() then return; end if;

  if v_existing then
    update public.friendships set requester_id = p_me, addressee_id = p_target, status = 'pending', ignored = false,
           created_at = now(), responded_at = null where id = v_row.id;
  else
    insert into public.friendships (requester_id, addressee_id) values (p_me, p_target);
  end if;
  perform private.notify(p_target, 'friend_request', jsonb_build_object('user_id', p_me));
end $$;

create function private.require_social(p_me uuid) returns void
language plpgsql security definer set search_path = '' as $$
begin
  -- Une personne en quarantaine peut utiliser l'app, pas solliciter les autres.
  if p_me is null or private.effective_status(p_me) <> 'active' then
    raise exception 'forbidden' using errcode = '42501';
  end if;
end $$;

create function public.send_friend_request(p_username text) returns text
language plpgsql security definer set search_path = '' as $$
declare
  v_me uuid := auth.uid();
begin
  perform private.require_social(v_me);
  perform private.rate_limit('friend_req:' || v_me, private.max_requests_per_day(), interval '1 day');
  perform private.rate_limit('friend_req_min:' || v_me, 6, interval '1 minute');
  perform private.request_friend(v_me, (select id from public.profiles where lower(username) = lower(btrim(p_username))), false);
  return 'ok';
end $$;

create function public.redeem_friend_code(p_code text) returns text
language plpgsql security definer set search_path = '' as $$
declare
  v_me uuid := auth.uid();
begin
  perform private.require_social(v_me);
  perform private.rate_limit('friend_req:' || v_me, private.max_requests_per_day(), interval '1 day');
  perform private.rate_limit('friend_req_min:' || v_me, 6, interval '1 minute');
  perform private.request_friend(v_me, (select id from public.profiles where friend_code = lower(btrim(p_code))), true);
  return 'ok';
end $$;

create function public.rotate_friend_code() returns text
language plpgsql security definer set search_path = '' as $$
declare
  v_code text := substr(replace(gen_random_uuid()::text, '-', ''), 1, 14);
begin
  if auth.uid() is null or not private.is_active(auth.uid()) then raise exception 'forbidden' using errcode = '42501'; end if;
  -- security definer : s'exécute en propriétaire, le garde-fou du client ne s'applique pas.
  update public.profiles set friend_code = v_code where id = auth.uid();
  return v_code;
end $$;

create function public.respond_friend_request(p_request uuid, p_action text) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_me uuid := auth.uid();
  v_row public.friendships;
begin
  perform private.require_social(v_me);
  select * into v_row from public.friendships where id = p_request and addressee_id = v_me and status = 'pending';
  if not found then raise exception 'request_not_found' using errcode = 'P0002'; end if;
  if p_action = 'accept' then
    if private.friend_count(v_me) >= private.max_friends() or private.friend_count(v_row.requester_id) >= private.max_friends() then
      raise exception 'friends_limit' using errcode = 'P0001';
    end if;
    update public.friendships set status = 'accepted', ignored = false, responded_at = now() where id = v_row.id;
    perform private.notify(v_row.requester_id, 'friend_accepted', jsonb_build_object('user_id', v_me));
  elsif p_action = 'decline' then
    -- Aucune notification à l'expéditeur.
    update public.friendships set status = 'declined', responded_at = now() where id = v_row.id;
  elsif p_action = 'ignore' then
    update public.friendships set ignored = true where id = v_row.id;
  else
    raise exception 'bad_action' using errcode = '22023';
  end if;
end $$;

create function public.cancel_friend_request(p_request uuid) returns void
language plpgsql security definer set search_path = '' as $$
begin
  delete from public.friendships where id = p_request and requester_id = auth.uid() and status in ('pending', 'declined');
end $$;

create function public.remove_friend(p_user uuid) returns void
language plpgsql security definer set search_path = '' as $$
begin
  delete from public.friendships f
   where f.status = 'accepted'
     and ((f.requester_id = auth.uid() and f.addressee_id = p_user) or (f.requester_id = p_user and f.addressee_id = auth.uid()));
end $$;

-- Bloquer : supprime le lien et interdit toute nouvelle demande, dans les deux sens.
create function public.block_user(p_user uuid) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_me uuid := auth.uid();
begin
  if v_me is null or not private.is_active(v_me) or p_user = v_me then raise exception 'forbidden' using errcode = '42501'; end if;
  if not exists (select 1 from public.profiles where id = p_user) then return; end if;
  perform private.rate_limit('block:' || v_me, 60, interval '1 day');
  delete from public.friendships f
   where (f.requester_id = v_me and f.addressee_id = p_user) or (f.requester_id = p_user and f.addressee_id = v_me);
  insert into public.friendships (requester_id, addressee_id, status, responded_at) values (v_me, p_user, 'blocked', now());
end $$;

create function public.unblock_user(p_user uuid) returns void
language plpgsql security definer set search_path = '' as $$
begin
  delete from public.friendships where status = 'blocked' and requester_id = auth.uid() and addressee_id = p_user;
end $$;

-- ── Listes (le seul moyen de voir d'autres comptes) ──────────────────────

create function public.list_friends() returns table (user_id uuid, username text, display_name text, avatar_url text, since timestamptz)
language sql stable security definer set search_path = '' as $$
  select p.id, p.username, p.display_name, p.avatar_url, f.responded_at
  from public.friendships f
  join public.profiles p on p.id = case when f.requester_id = auth.uid() then f.addressee_id else f.requester_id end
  where f.status = 'accepted' and auth.uid() in (f.requester_id, f.addressee_id)
    and private.is_active(auth.uid()) and private.is_visible(p.id)
  order by lower(p.username)
$$;

-- direction : in (reçues) | out (envoyées). Une demande refusée reste « en
-- attente » côté expéditeur : on ne lui dit pas qu'elle a été refusée.
create function public.list_friend_requests() returns table (id uuid, direction text, user_id uuid, username text, display_name text, avatar_url text, created_at timestamptz)
language sql stable security definer set search_path = '' as $$
  select f.id, 'in', p.id, p.username, p.display_name, p.avatar_url, f.created_at
  from public.friendships f join public.profiles p on p.id = f.requester_id
  where f.addressee_id = auth.uid() and f.status = 'pending' and not f.ignored
    and private.is_active(auth.uid()) and private.is_visible(p.id)
  union all
  select f.id, 'out', p.id, p.username, p.display_name, p.avatar_url, f.created_at
  from public.friendships f join public.profiles p on p.id = f.addressee_id
  where f.requester_id = auth.uid() and f.status in ('pending', 'declined')
    and private.is_active(auth.uid()) and private.is_visible(p.id)
  order by created_at desc
$$;

create function public.list_blocked() returns table (user_id uuid, username text, avatar_url text)
language sql stable security definer set search_path = '' as $$
  select p.id, p.username, p.avatar_url
  from public.friendships f join public.profiles p on p.id = f.addressee_id
  where f.requester_id = auth.uid() and f.status = 'blocked' and private.is_active(auth.uid())
  order by lower(p.username)
$$;

-- Fiche d'un compte, selon ce que ses réglages m'autorisent. Pas de recherche :
-- il faut déjà connaître l'identifiant (amis, participants d'une session…).
create function public.get_profile(p_user uuid) returns jsonb
language plpgsql stable security definer set search_path = '' as $$
declare
  v_me uuid := auth.uid();
  p public.profiles;
begin
  if not private.can_view(v_me, p_user, 'profile_min') then return null; end if;
  select * into p from public.profiles where id = p_user;
  return jsonb_build_object('id', p.id, 'username', p.username, 'avatar_url', p.avatar_url)
      || case when private.can_view(v_me, p_user, 'profile_full')
              then jsonb_build_object('display_name', p.display_name, 'bio', p.bio, 'friend', private.are_friends(v_me, p_user))
              else '{}'::jsonb end;
end $$;
