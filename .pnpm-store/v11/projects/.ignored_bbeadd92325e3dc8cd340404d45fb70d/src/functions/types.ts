export interface CustomFunction {
  name: string;
  description: string;
  created_at: string;
  code: string;
}

export interface FunctionRunResult {
  ok: boolean;
  result?: unknown;
  error?: string;
  stdout?: string;
  stderr?: string;
}
