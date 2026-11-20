-- A private conversion ledger, independent of the existing document-reading trial.
create table if not exists public.nibras_media_jobs (
    id uuid primary key,
    account text not null,
    quota_period text not null,
    state text not null default 'pending' check (state in ('pending','finished','failed')),
    provider_id uuid,
    created_at timestamptz not null default now(),
    result_url text,
    result_name text,
    chat_id text,
    prompt text
);
alter table public.nibras_media_jobs enable row level security;
revoke all on public.nibras_media_jobs from public, anon, authenticated;
grant select, insert, update, delete on public.nibras_media_jobs to service_role;
create index if not exists media_quota_lookup on public.nibras_media_jobs(account,quota_period,state);

create or replace function public.reserve_nibras_media(
    p_id uuid, p_account text, p_period text, p_limit integer, p_chat text, p_prompt text
) returns text language plpgsql set search_path = public as $$
begin
    perform pg_advisory_xact_lock(hashtextextended(p_account,0));
    if exists(select 1 from nibras_media_jobs where id=p_id) then
        return 'duplicate';
    end if;
    if exists(select 1 from nibras_media_jobs where account=p_account and state='pending') then
        return 'busy';
    end if;
    if (select count(*) from nibras_media_jobs where account=p_account and quota_period=p_period
        and state='finished') >= p_limit then
        return 'exhausted';
    end if;
    insert into nibras_media_jobs(id,account,quota_period,chat_id,prompt)
        values(p_id,p_account,p_period,p_chat,p_prompt);
    return 'reserved';
end $$;
revoke all on function public.reserve_nibras_media(uuid,text,text,integer,text,text)
    from public, anon, authenticated;
grant execute on function public.reserve_nibras_media(uuid,text,text,integer,text,text) to service_role;
