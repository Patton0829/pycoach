import type { QuestionMetadata as QuestionMetadataValue } from "../types/session";
import { DifficultyStars } from "./DifficultyStars";

export function QuestionMetadata({
  metadata,
}: {
  metadata: QuestionMetadataValue;
}) {
  const source = metadata.source;

  return (
    <div className="question-metadata" role="group" aria-label="题目信息">
      <div className="question-metadata__details">
        <span className="question-metadata__difficulty">
          难度 <DifficultyStars difficulty={metadata.difficulty} />
        </span>
        {metadata.knowledge_points.length > 0 && (
          <span>
            知识点：{metadata.knowledge_points.map((point) => point.name).join("、")}
          </span>
        )}
      </div>
      {source && (
        <div className="question-metadata__source">
          来源：{source.title}
          {source.exam_year !== null && ` · ${source.exam_year} 年`}
          {` · ${source.document_type === "sample_exam" ? "样题" : "历年真题"}`}
          {` · 第 ${source.question_number} 题`}
          {source.pdf_pages.length > 0 && ` · PDF 第 ${source.pdf_pages.join("、")} 页`}
        </div>
      )}
    </div>
  );
}
