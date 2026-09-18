import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/store/toast-store";

import {
  getKnowledgeArticle,
  getRelatedKnowledgeArticles,
  listKnowledgeArticles,
  listKnowledgeCategories,
  submitKnowledgeArticleFeedback,
  uploadKnowledgeDocument,
} from "./api";

export function useKnowledgeCategories() {
  return useQuery({ queryKey: ["knowledge-categories"], queryFn: listKnowledgeCategories });
}

export function useKnowledgeArticles(params: { category?: string; q?: string; sort?: "recent" | "popular"; limit?: number }) {
  return useQuery({
    queryKey: ["knowledge-articles", params],
    queryFn: () => listKnowledgeArticles(params),
  });
}

export function useKnowledgeArticle(articleId: string | undefined) {
  return useQuery({
    queryKey: ["knowledge-article", articleId],
    queryFn: () => getKnowledgeArticle(articleId as string),
    enabled: !!articleId,
  });
}

export function useRelatedKnowledgeArticles(articleId: string | undefined) {
  return useQuery({
    queryKey: ["knowledge-article", articleId, "related"],
    queryFn: () => getRelatedKnowledgeArticles(articleId as string),
    enabled: !!articleId,
  });
}

export function useSubmitKnowledgeFeedback(articleId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (helpful: boolean) => submitKnowledgeArticleFeedback(articleId, helpful),
    onSuccess: () => {
      toast.success("Thanks for the feedback");
      queryClient.invalidateQueries({ queryKey: ["knowledge-article", articleId] });
    },
    onError: (error) => toast.error("Couldn't submit feedback", error instanceof Error ? error.message : undefined),
  });
}

export function useUploadKnowledgeDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: uploadKnowledgeDocument,
    onSuccess: (article) => {
      toast.success("Article added", `"${article.title}" is now searchable and available to the AI.`);
      queryClient.invalidateQueries({ queryKey: ["knowledge-categories"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-articles"] });
    },
    onError: (error) => toast.error("Upload failed", error instanceof Error ? error.message : undefined),
  });
}
