export interface CustomSkillToolDependency {
  capability: string;
  label: string;
  status: "available" | "missing";
  type?: "custom_function" | "mcp";
  name?: string;
  server?: string;
  instruction?: string;
}

export interface CustomSkillTooling {
  required: CustomSkillToolDependency[];
  created_functions: Array<{
    capability: string;
    name: string;
    type: "custom_function";
  }>;
  reused_tools: CustomSkillToolDependency[];
}

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
  tooling?: CustomSkillTooling;
  skill_md?: string;
}
