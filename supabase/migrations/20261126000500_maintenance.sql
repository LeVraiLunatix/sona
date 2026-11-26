-- Sona : rétention (RGPD), export des données, file de scrobbling, tâches planifiées.

-- ── File de scrobbling Last.fm (consommée par sona-accounts, avec réessais) ─

create table private.scrobble_queue (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles (id) on delete cascade,
  kind text not null check (kind in ('scrobble', 'now_playing')),
  payload jsonb not null,
  attempts int not null default 0,
  next_attempt_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);
create index scrobble_queue_due_idx on private.scrobble_queue (next_attempt_at);
alter table private.scrobble_queue enable row level security;

-- ── Export RGPD : toutes mes données, même après un avertissement ou un ban ─

create function private.export_data(v_me uuid) returns jsonb
language plpgsql stable security definer set search_path = '' as $$
begin
  return jsonb_build_object(
    'exported_at', now(),
    'profile', (select to_jsonb(p) - 'id' from public.profiles p where p.id = v_me),
    'settings', (select to_jsonb(s) - 'user_id' from public.user_settings s where s.user_id = v_me),
    'privacy', (select to_jsonb(s) - 'user_id' from public.privacy_settings s where s.user_id = v_me),
    'connected_services', coalesce((select jsonb_agg(jsonb_build_object('provider', c.provider, 'username', c.external_username, 'connected_at', c.connected_at))
                                    from public.connected_services c where c.user_id = v_me), '[]'),
    'passkeys', coalesce((select jsonb_agg(jsonb_build_object('device', k.device_name, 'created_at', k.created_at)) from public.passkey_credentials k where k.user_id = v_me), '[]'),
    'friendships', coalesce((select jsonb_agg(jsonb_build_object('status', f.status, 'since', f.created_at,
                               'with', (select p.username from public.profiles p where p.id = case when f.requester_id = v_me then f.addressee_id else f.requester_id end),
                               'sent_by_me', f.requester_id = v_me))
                             from public.friendships f
                             where v_me in (f.requester_id, f.addressee_id)
                               and not (f.status = 'blocked' and f.addressee_id = v_me)
                               and not (f.status = 'declined' and f.requester_id = v_me)), '[]'),
    'notifications', coalesce((select jsonb_agg(to_jsonb(n) - 'user_id') from public.notifications n where n.user_id = v_me), '[]'),
    'reports_made', coalesce((select jsonb_agg(jsonb_build_object('target_type', r.target_type, 'reason', r.reason, 'status', r.status, 'created_at', r.created_at))
                              from public.reports r where r.reporter_id = v_me), '[]'),
    'sanctions', coalesce((select jsonb_agg(to_jsonb(s) - 'user_id') from public.sanctions s where s.user_id = v_me), '[]'),
    'appeals', coalesce((select jsonb_agg(to_jsonb(a) - 'user_id') from public.appeals a where a.user_id = v_me), '[]')
  );
end $$;
create function public.export_my_data() returns jsonb
language plpgsql stable security definer set search_path = '' as $$
begin
  if auth.uid() is null then raise exception 'forbidden' using errcode = '42501'; end if;
  return private.export_data(auth.uid());
end $$;
grant execute on function public.export_my_data() to authenticated;

create function public.service_export(p_user uuid) returns jsonb
language plpgsql stable security definer set search_path = '' as $$
begin
  perform private.only_service();
  return private.export_data(p_user);
end $$;

-- ── Rétention : durées définies une fois pour toutes ─────────────────────
--   rate_limits 2 j · signup_events 30 j · notifications lues 30 j (toutes 180 j)
--   signalements clos 180 j · contestations traitées 12 mois · refus d'amitié 90 j
--   audit_log 12 mois · file de scrobbling 7 j · alertes envoyées 30 j

create function public.purge_expired() returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_expired int; v_audit int;
begin
  perform private.only_service();
  -- Suspensions arrivées à terme.
  update public.sanctions set revoked_at = expires_at, revoke_reason = 'expirée'
   where kind = 'suspension' and revoked_at is null and expires_at <= now();
  update public.profiles set status = 'active', status_reason = null, status_until = null
   where status = 'suspended' and status_until is not null and status_until <= now();
  get diagnostics v_expired = row_count;

  delete from private.rate_limits where window_start < now() - interval '2 days';
  delete from private.signup_events where at < now() - interval '30 days';
  delete from private.passkey_challenges where expires_at < now();
  delete from private.banned_identifiers where expires_at is not null and expires_at < now();
  delete from private.scrobble_queue where created_at < now() - interval '7 days';
  delete from public.notifications where (read_at is not null and read_at < now() - interval '30 days') or created_at < now() - interval '180 days';
  delete from public.reports where status in ('resolved', 'dismissed') and resolved_at < now() - interval '180 days';
  delete from public.appeals where status <> 'open' and handled_at < now() - interval '12 months';
  delete from public.friendships where status = 'declined' and responded_at < now() - interval '90 days';
  delete from public.admin_alerts where sent_at is not null and sent_at < now() - interval '30 days';

  perform set_config('sona.retention_purge', 'on', true);
  delete from public.audit_log where at < now() - interval '12 months';
  get diagnostics v_audit = row_count;
  perform set_config('sona.retention_purge', 'off', true);
  return jsonb_build_object('suspensions_expired', v_expired, 'audit_rows_purged', v_audit);
end $$;
grant execute on function public.purge_expired() to service_role;

-- ── Domaines d'e-mails jetables courants (liste modifiable depuis l'admin) ─

insert into private.disposable_domains (domain) values
  ('mailinator.com'), ('guerrillamail.com'), ('guerrillamail.net'), ('guerrillamail.org'), ('sharklasers.com'),
  ('10minutemail.com'), ('10minutemail.net'), ('tempmail.com'), ('temp-mail.org'), ('temp-mail.io'),
  ('yopmail.com'), ('yopmail.fr'), ('yopmail.net'), ('throwawaymail.com'), ('trashmail.com'), ('trashmail.net'),
  ('getnada.com'), ('nada.email'), ('maildrop.cc'), ('dispostable.com'), ('fakeinbox.com'), ('mailnesia.com'),
  ('mintemail.com'), ('mytemp.email'), ('tempail.com'), ('tempinbox.com'), ('tempr.email'), ('discard.email'),
  ('spamgourmet.com'), ('mohmal.com'), ('emailondeck.com'), ('burnermail.io'), ('moakt.com'), ('mailcatch.com'),
  ('jetable.org'), ('jetable.fr.nf'), ('courriel.fr.nf'), ('trbvm.com'), ('1secmail.com'), ('1secmail.net'),
  ('1secmail.org'), ('inboxkitten.com'), ('harakirimail.com'), ('mailforspam.com'), ('spambox.us'),
  ('tmpmail.org'), ('tmpmail.net'), ('emailfake.com'), ('crazymailing.com'), ('fexbox.org')
on conflict do nothing;

-- ── Pseudos réservés et mots interdits (point de départ, à compléter) ────
-- Comparés après normalisation (accents, « leet speak » et séparateurs retirés),
-- en sous-chaîne pour les mots offensants : on évite donc les termes courts qui
-- se cachent dans des prénoms (« dominique », « nazim », « torpedo »).

insert into private.forbidden_terms (term, kind) values
  ('admin', 'reserved'), ('administrator', 'reserved'), ('administrateur', 'reserved'), ('moderator', 'reserved'),
  ('moderateur', 'reserved'), ('modo', 'reserved'), ('support', 'reserved'), ('sona', 'reserved'), ('trysona', 'reserved'),
  ('staff', 'reserved'), ('system', 'reserved'), ('systeme', 'reserved'), ('root', 'reserved'), ('official', 'reserved'),
  ('officiel', 'reserved'), ('lunatix', 'reserved'), ('anonymous', 'reserved'), ('null', 'reserved'), ('undefined', 'reserved'),
  ('hitler', 'offensive'), ('nazism', 'offensive'), ('pedophile', 'offensive'),
  ('rapist', 'offensive'), ('violeur', 'offensive'), ('nigger', 'offensive'), ('nigga', 'offensive'),
  ('negre', 'offensive'), ('fagot', 'offensive'), ('faggot', 'offensive'), ('tarlouze', 'offensive'),
  ('salope', 'offensive'), ('connard', 'offensive'), ('enculer', 'offensive'),
  ('fuckyou', 'offensive'), ('killyourself', 'offensive')
on conflict do nothing;

-- ── Tâches planifiées (seulement si pg_cron est activé : Database > Extensions) ─

do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    perform cron.schedule('sona-purge', '17 3 * * *', 'select public.purge_expired()');
    perform cron.schedule('sona-signup-spike', '*/10 * * * *', 'select private.detect_signup_spike()');
  end if;
end $$;

-- ── Invités inactifs (connexion anonyme) : supprimés après 30 jours ─────
-- La suppression elle-même (et celle des données musicales) est faite par
-- sona-accounts, qui lit cette liste.

create function public.service_expired_guests(p_days int default 30) returns uuid[]
language plpgsql stable security definer set search_path = '' as $$
begin
  perform private.only_service();
  return coalesce((select array_agg(u.id) from auth.users u
                   where u.is_anonymous and coalesce(u.last_sign_in_at, u.created_at) < now() - make_interval(days => p_days)
                   limit 500), '{}');
end $$;
grant execute on function public.service_expired_guests(int) to service_role;

-- ── Photos de profil (Supabase Storage, seulement si le stockage existe) ─
-- Lecture publique, écriture réservée au dossier de l'utilisateur, 200 Ko max, images seulement.

do $$
begin
  if to_regclass('storage.buckets') is not null then
    insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    values ('avatars', 'avatars', true, 204800, array['image/webp', 'image/jpeg', 'image/png'])
    on conflict (id) do update set public = true, file_size_limit = 204800,
      allowed_mime_types = array['image/webp', 'image/jpeg', 'image/png'];

    execute 'drop policy if exists avatars_insert on storage.objects';
    execute 'drop policy if exists avatars_update on storage.objects';
    execute 'drop policy if exists avatars_delete on storage.objects';
    execute $p$create policy avatars_insert on storage.objects for insert to authenticated
      with check (bucket_id = 'avatars' and (storage.foldername(name))[1] = auth.uid()::text and public.me_active())$p$;
    execute $p$create policy avatars_update on storage.objects for update to authenticated
      using (bucket_id = 'avatars' and (storage.foldername(name))[1] = auth.uid()::text and public.me_active())$p$;
    execute $p$create policy avatars_delete on storage.objects for delete to authenticated
      using (bucket_id = 'avatars' and (storage.foldername(name))[1] = auth.uid()::text)$p$;
  end if;
end $$;
