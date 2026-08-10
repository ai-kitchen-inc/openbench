export interface CustomSkill {
  id: string;
  name: string;
  description: string;
  triggers: string[];
  instructions: string;
  version: string;
  created_at: string;
  updated_at: string;
  source: string;
  context_chars: number;
  skill_md?: string;
}
