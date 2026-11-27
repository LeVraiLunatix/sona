-- Photos de profil : l'envoi avec remplacement (upsert) exige aussi le droit de LIRE ses propres
-- objets. Sans cette règle : « new row violates row-level security policy ».
-- La lecture publique des photos passe par l'adresse publique du bucket, pas par cette règle.

do $$
begin
  if to_regclass('storage.objects') is not null then
    execute 'drop policy if exists avatars_select on storage.objects';
    execute $p$create policy avatars_select on storage.objects for select to authenticated
      using (bucket_id = 'avatars' and (storage.foldername(name))[1] = auth.uid()::text)$p$;
  end if;
end $$;
