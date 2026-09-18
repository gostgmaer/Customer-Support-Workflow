import { apiFetch, apiUpload } from "@/lib/api/client";
import type { KnowledgeArticleDetail, KnowledgeArticleSummary, KnowledgeCategorySummary } from "@/types/api";

export function listKnowledgeCategories() {
  return apiFetch<KnowledgeCategorySummary[]>("/api/v1/knowledge/categories");
}

export function listKnowledgeArticles(
  params: { category?: string; q?: string; sort?: "recent" | "popular"; limit?: number } = {}
) {
  return apiFetch<KnowledgeArticleSummary[]>("/api/v1/knowledge/articles", { query: params });
}

export function getKnowledgeArticle(articleId: string) {
  return apiFetch<KnowledgeArticleDetail>(`/api/v1/knowledge/articles/${articleId}`);
}

export function getRelatedKnowledgeArticles(articleId: string) {
  return apiFetch<KnowledgeArticleSummary[]>(`/api/v1/knowledge/articles/${articleId}/related`);
}

export function submitKnowledgeArticleFeedback(articleId: string, helpful: boolean) {
  return apiFetch<KnowledgeArticleDetail>(`/api/v1/knowledge/articles/${articleId}/feedback`, {
    method: "POST",
    body: { helpful },
  });
}

export function uploadKnowledgeDocument(input: { title: string; category: string; file: File }) {
  const formData = new FormData();
  formData.set("title", input.title);
  formData.set("category", input.category);
  formData.set("file", input.file);
  return apiUpload<KnowledgeArticleDetail>("/api/v1/knowledge/upload", formData);
}
