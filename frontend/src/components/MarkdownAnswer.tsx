"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function MarkdownAnswer({ content }: { content: string }) {
  return (
    <div className="prose prose-invert prose-sm max-w-none text-slate-100 prose-headings:mb-2 prose-headings:mt-3 prose-headings:font-semibold prose-headings:text-white prose-p:my-1.5 prose-p:leading-relaxed prose-ul:my-1.5 prose-ul:list-disc prose-ul:pl-5 prose-ol:my-1.5 prose-ol:list-decimal prose-ol:pl-5 prose-li:my-0.5 prose-strong:text-white prose-code:rounded prose-code:bg-slate-800 prose-code:px-1 prose-code:py-0.5 prose-code:text-sky-200 prose-pre:rounded-xl prose-pre:border prose-pre:border-slate-800 prose-pre:bg-slate-950 prose-pre:p-3 prose-a:text-sky-400">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}
