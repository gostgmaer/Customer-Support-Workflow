"use client";

import { useId, useState } from "react";
import type { FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { FieldError, Label } from "@/components/ui/Label";
import { Input } from "@/components/ui/Input";
import { useKnowledgeCategories, useUploadKnowledgeDocument } from "@/features/knowledge/hooks";
import { getErrorMessage } from "@/lib/api/get-error-message";

export function UploadArticleDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const categoriesListId = useId();
  const categories = useKnowledgeCategories();
  const upload = useUploadKnowledgeDocument();

  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fieldError, setFieldError] = useState<string | undefined>(undefined);

  const close = () => {
    setTitle("");
    setCategory("");
    setFile(null);
    setFieldError(undefined);
    upload.reset();
    onClose();
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!file) {
      setFieldError("Choose a file to upload");
      return;
    }
    setFieldError(undefined);
    upload.mutate({ title, category, file }, { onSuccess: close });
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title="Add a knowledge base article"
      description="Uploads a Markdown, text, PDF, or Word file into the same pipeline the AI retrieves from during chat."
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {upload.isError && <Alert variant="error">{getErrorMessage(upload.error)}</Alert>}

        <div>
          <Label htmlFor="kb-title">Title</Label>
          <Input
            id="kb-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Return Policy"
            required
          />
        </div>

        <div>
          <Label htmlFor="kb-category">Category</Label>
          <Input
            id="kb-category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="e.g. refunds"
            list={categoriesListId}
            required
          />
          <datalist id={categoriesListId}>
            {categories.data?.map((c) => <option key={c.category} value={c.category} />)}
          </datalist>
        </div>

        <div>
          <Label htmlFor="kb-file">File (.md, .txt, .pdf, or .docx - max 10MB)</Label>
          <input
            id="kb-file"
            type="file"
            accept=".md,.markdown,.txt,.pdf,.docx,text/markdown,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm text-foreground file:mr-3 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-secondary-foreground hover:file:bg-muted"
          />
          {file && <p className="mt-1.5 text-xs text-muted-foreground">{file.name}</p>}
          <FieldError>{fieldError}</FieldError>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={close}>
            Cancel
          </Button>
          <Button type="submit" isLoading={upload.isPending}>
            Upload
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
