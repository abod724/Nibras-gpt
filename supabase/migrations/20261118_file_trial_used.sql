-- One-time file-task trial for registered users; admins bypass this flag.
ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS file_trial_used boolean NOT NULL DEFAULT false;
