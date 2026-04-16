create table if not exists public.venues (
    id bigint generated always as identity primary key,
    name text not null,
    city text,
    admin_area text,
    region text,
    country text,
    address text,
    custom_area text,
    category text,
    target_mood text,
    contact_person text,
    contact_role text,
    phone text,
    whatsapp text,
    email text,
    instagram text,
    website text,
    active_events boolean not null default false,
    seasonality text,
    status text not null default 'da scremare',
    priority text,
    notes text,
    tags_json text not null default '[]',
    next_action text,
    follow_up_date date,
    inserted_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.venue_activities (
    id bigint generated always as identity primary key,
    venue_id bigint not null references public.venues(id) on delete cascade,
    activity_type text not null,
    title text not null,
    details text,
    created_at timestamptz not null default now()
);

create table if not exists public.booking_dates (
    id bigint generated always as identity primary key,
    venue_id bigint not null references public.venues(id) on delete cascade,
    event_title text not null,
    event_date date not null,
    status text not null default 'confirmed',
    notes text,
    created_at timestamptz not null default now()
);

create index if not exists venues_status_idx on public.venues(status);
create index if not exists venues_priority_idx on public.venues(priority);
create index if not exists venues_follow_up_idx on public.venues(follow_up_date);
create index if not exists venue_activities_venue_id_idx on public.venue_activities(venue_id);
create index if not exists booking_dates_venue_id_idx on public.booking_dates(venue_id);

alter table public.venues enable row level security;
alter table public.venue_activities enable row level security;
alter table public.booking_dates enable row level security;

drop policy if exists "Allow anon read venues" on public.venues;
create policy "Allow anon read venues" on public.venues for select using (true);

drop policy if exists "Allow anon read venue_activities" on public.venue_activities;
create policy "Allow anon read venue_activities" on public.venue_activities for select using (true);

drop policy if exists "Allow anon read booking_dates" on public.booking_dates;
create policy "Allow anon read booking_dates" on public.booking_dates for select using (true);
