-- Connexion d'une application par le navigateur : code à usage unique, valable une minute,
-- lié au défi (empreinte) de l'application qui l'a demandé. Écrit et lu par sona-accounts seul.

create table private.app_links (
  code_hash text primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  challenge text not null,
  expires_at timestamptz not null default now() + interval '60 seconds'
);
alter table private.app_links enable row level security;
