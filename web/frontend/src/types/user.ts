export type SpeakerGuardSummary = {
  same_person?: boolean | null;
  confidence?: number | null;
  alert?: boolean;
  signals?: string[];
  reason?: string;
  alerts_count?: number;
};

export type UserProfileSummary = {
  name?: string;
  how_to_address?: string;
  personality_type?: string;
  character?: string[];
  peculiarities?: string[];
  mood?: string;
  mood_previous?: string;
  likes?: string[];
  dislikes?: string[];
  time_habits?: string[];
  current_state?: string;
  energy?: string;
  facts_count?: number;
  evidence_count?: number;
  bond?: "early" | "growing" | "attached" | string;
  inner_circle?: { name?: string; role?: string }[];
  updated_at?: string;
  style_ready?: boolean;
  style_samples?: number;
  speaker?: SpeakerGuardSummary;
};
