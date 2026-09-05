/**
 * Typed API client.
 *
 * Backend errors arrive as `{error: {code, message, detail}}` and are rethrown
 * as `WorkspaceApiError` so the UI can show the real reason — "no web search
 * provider is configured" is information the researcher needs, not noise to
 * swallow behind a generic failure toast.
 */
import type {
  Answer, Capabilities, ChartSpec, Diagram, Graph, Message, Note, Project,
  ProvidersReport, Source,
} from "./types";

export class WorkspaceApiError extends Error {
  code: string;
  detail: Record<string, unknown>;
  status: number;

  constructor(message: string, code: string, detail: Record<string, unknown>, status: number) {
    super(message);
    this.name = "WorkspaceApiError";
    this.code = code;
    this.detail = detail;
    this.status = status;
  }
}

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, {
    ...init,
    headers:
      init?.body instanceof FormData
        ? init?.headers
        : { "Content-Type": "application/json", ...(init?.headers || {}) },
  });

  if (response.status === 204) return undefined as T;

  const isJson = (response.headers.get("content-type") || "").includes("json");
  if (!response.ok) {
    if (isJson) {
      const body = await response.json().catch(() => null);
      const err = body?.error;
      throw new WorkspaceApiError(
        err?.message || `Request failed (${response.status})`,
        err?.code || "http_error",
        err?.detail || {},
        response.status,
      );
    }
    throw new WorkspaceApiError(
      `${response.status} ${response.statusText}`, "http_error", {}, response.status,
    );
  }
  return (isJson ? await response.json() : ((await response.text()) as unknown)) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

/** Trigger a browser download from a binary endpoint. */
async function download(path: string, body: unknown, fallbackName: string): Promise<void> {
  const response = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new WorkspaceApiError(
      payload?.error?.message || "Export failed", payload?.error?.code || "export_failed",
      payload?.error?.detail || {}, response.status,
    );
  }
  const disposition = response.headers.get("content-disposition") || "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = match?.[1] || fallbackName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  /* system */
  providers: () => request<ProvidersReport>("/providers"),
  capabilities: () => request<Capabilities>("/capabilities"),

  /* projects */
  listProjects: () => request<Project[]>("/projects"),
  createProject: (body: { name: string; question?: string; description?: string }) =>
    post<Project>("/projects", body),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  updateProject: (id: string, body: Partial<Project>) =>
    request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: "DELETE" }),

  /* sources */
  listSources: (projectId: string, style = "apa") =>
    request<{ items: Source[]; total: number }>(`/projects/${projectId}/sources?style=${style}`),
  getSource: (projectId: string, sourceId: string) =>
    request<Source & { citations: Record<string, string> }>(
      `/projects/${projectId}/sources/${sourceId}`,
    ),
  updateSource: (projectId: string, sourceId: string, patch: { starred?: boolean; excluded?: boolean }) =>
    request<{ id: string; starred: boolean; excluded: boolean }>(
      `/projects/${projectId}/sources/${sourceId}?` +
        new URLSearchParams(
          Object.entries(patch).map(([k, v]) => [k, String(v)]),
        ).toString(),
      { method: "PATCH" },
    ),
  deleteSource: (projectId: string, sourceId: string) =>
    request<void>(`/projects/${projectId}/sources/${sourceId}`, { method: "DELETE" }),
  sourcePassages: (sourceId: string) =>
    request<{ total: number; items: { id: string; text: string; locator: string }[] }>(
      `/files/${sourceId}/passages`,
    ),

  /* research */
  research: (body: Record<string, unknown>) => post<Answer>("/research", body),
  analyseUrl: (body: { url: string; project_id?: string | null }) => post<any>("/url", body),
  analyseVideo: (body: { url: string; project_id?: string | null; question?: string | null }) =>
    post<any>("/video", body),
  analysePaper: (body: Record<string, unknown>) => post<any>("/papers/analyse", body),
  synthesise: (body: { project_id: string; source_ids?: string[]; question?: string | null }) =>
    post<any>("/papers/synthesise", body),

  /* conversation & notes */
  messages: (projectId: string) =>
    request<{ items: Message[] }>(`/projects/${projectId}/messages`),
  notes: (projectId: string) => request<{ items: Note[] }>(`/projects/${projectId}/notes`),
  createNote: (projectId: string, body: Partial<Note>) =>
    post<{ id: string }>(`/projects/${projectId}/notes`, body),
  deleteNote: (projectId: string, noteId: string) =>
    request<void>(`/projects/${projectId}/notes/${noteId}`, { method: "DELETE" }),
  timeline: (projectId: string) =>
    request<{ items: { kind: string; summary: string; created_at: string }[] }>(
      `/projects/${projectId}/timeline`,
    ),
  artifacts: (projectId: string, kind?: string) =>
    request<{ items: { id: string; kind: string; title: string; payload: any; revision: number }[] }>(
      `/projects/${projectId}/artifacts${kind ? `?kind=${kind}` : ""}`,
    ),
  recall: (projectId: string, q: string) =>
    request<any>(`/projects/${projectId}/recall?q=${encodeURIComponent(q)}`),
  graph: (projectId: string, node?: string) =>
    request<Graph>(`/projects/${projectId}/graph${node ? `?node=${encodeURIComponent(node)}` : ""}`),

  /* files & images */
  uploadFiles: (projectId: string, files: File[]) => {
    const form = new FormData();
    form.append("project_id", projectId);
    files.forEach((file) => form.append("files", file));
    return request<{ uploaded: any[]; failed: any[]; summary: string }>("/files", {
      method: "POST",
      body: form,
    });
  },
  fileUrl: (sourceId: string) => `${BASE}/files/${sourceId}/raw`,
  analyseImage: (sourceId: string, question?: string, kind = "auto") =>
    post<any>(
      `/images/${sourceId}/analyse?kind=${kind}` +
        (question ? `&question=${encodeURIComponent(question)}` : ""),
    ),
  compareImages: (sourceIds: string[], question?: string) =>
    post<any>(
      `/images/compare${question ? `?question=${encodeURIComponent(question)}` : ""}`,
      sourceIds,
    ),

  /* data */
  datasetColumns: (sourceId: string) => request<any>(`/datasets/${sourceId}/columns`),
  analyse: (body: Record<string, unknown>) => post<any>("/analysis", body),
  recommendChart: (body: Record<string, unknown>) => post<any>("/charts/recommend", body),
  chart: (body: Record<string, unknown>) => post<ChartSpec>("/charts", body),
  renderChart: (body: Record<string, unknown>, fmt = "png") =>
    download(`/charts/render?fmt=${fmt}`, body, `chart.${fmt}`),

  /* diagrams */
  diagramKinds: () => request<any>("/diagrams/kinds"),
  createDiagram: (body: Record<string, unknown>) => post<Diagram>("/diagrams", body),
  reviseDiagram: (id: string, instruction: string) =>
    post<Diagram>(`/diagrams/${id}/revise`, { instruction }),

  /* citations & export */
  citationStyles: () => request<any>("/citations/styles"),
  formatCitations: (body: { project_id: string; source_ids?: string[]; style: string }) =>
    post<any>("/citations/format", body),
  exportCitations: (body: { project_id: string; source_ids?: string[]; style: string }, fmt: string) =>
    download(`/citations/export?fmt=${fmt}`, body, `references.${fmt}`),
  exportFormats: () => request<any>("/export/formats"),
  exportAnswer: (body: Record<string, unknown>) =>
    download("/export", body, `research.${body.format}`),
};
