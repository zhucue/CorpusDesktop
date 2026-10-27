import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";
import { MAX_PAGE_SIZE, api, type Page, type Project } from "./api";

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get<Page<Project>>("/projects", { page_size: MAX_PAGE_SIZE }),
  });
}

export function useProjectId(): string {
  return useParams().projectId!;
}

export function useProject() {
  const id = useProjectId();
  return useQuery({ queryKey: ["project", id], queryFn: () => api.get<Project>(`/projects/${id}`) });
}

export function canEdit(p?: Project): boolean {
  return p?.role === "owner" || p?.role === "editor";
}
