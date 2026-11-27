-- Un pseudo réservé peut avoir des propriétaires : eux seuls peuvent le prendre.
-- Les adresses se saisissent directement en base (jamais dans le dépôt) :
--   update private.forbidden_terms set owners = array['moi@exemple.fr'] where term = 'lunatix';

alter table private.forbidden_terms add column owners text[] not null default '{}';  -- e-mails en minuscules

insert into private.forbidden_terms (term, kind) values ('lunatix', 'reserved'), ('lvnatixx', 'reserved')
on conflict do nothing;

create or replace function private.name_problem(p_text text) returns text
language plpgsql stable security definer set search_path = '' as $$
declare
  n text := private.normalize_name(p_text);
begin
  if p_text is null or p_text !~ '^[A-Za-z0-9_.-]{3,20}$' then return 'format'; end if;
  if exists (select 1 from private.forbidden_terms t where t.kind = 'reserved' and t.term = n
             and not exists (select 1 from auth.users u where u.id = auth.uid() and lower(u.email) = any (t.owners))) then return 'reserved'; end if;
  if exists (select 1 from private.forbidden_terms t where t.kind = 'offensive' and position(t.term in n) > 0) then return 'offensive'; end if;
  return null;
end $$;
