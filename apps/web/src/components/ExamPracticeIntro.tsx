import { useEffect, useState } from "react";
import { getExamPapers } from "../api/client";
import type { ExamPaperSummary } from "../types/session";

const questionTypeLabels: Record<string, string> = {
  multiple_choice: "选择题",
  code_blank: "代码填空",
  output_prediction: "输出预测",
  short_explanation: "简答题",
  programming: "编程题",
};

export function ExamPracticeIntro({
  onStart,
  onContinue,
  canContinue,
  disabled,
}: {
  onStart: (sourceDocumentId: string) => void;
  onContinue: () => void;
  canContinue: boolean;
  disabled: boolean;
}) {
  const [papers, setPapers] = useState<ExamPaperSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void getExamPapers()
      .then((result) => {
        if (!cancelled) setPapers(result);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const availableCount = papers.reduce(
    (total, paper) => total + paper.available_question_count, 0,
  );
  const excludedCount = papers.reduce(
    (total, paper) => total + paper.excluded_question_count, 0,
  );

  return (
    <section className="exam-intro" aria-labelledby="exam-title">
      <div className="diagnostic-intro__hero">
        <span>原卷题目 · 自适应练习</span>
        <h1 id="exam-title">真题测试</h1>
        <p>
          从已审核的试卷中选题，结合你的知识点掌握情况安排练习顺序。
          每道题展示五星难度、评估知识点和原卷来源；作答后由 Critic 评价与讲解。
        </p>
        <p className="exam-intro__instructions">
          在同一个输入框中回答、追问，或输入“下一题”“结束学习”。
          有效评估按每个知识点的累计 20 题规则记录掌握度。
        </p>
        {canContinue && (
          <div className="diagnostic-intro__actions">
            <button
              type="button"
              className="secondary-action"
              onClick={onContinue}
              disabled={disabled}
            >
              继续真题测试
            </button>
          </div>
        )}
      </div>

      {loading ? (
        <p className="exam-catalog-notice" role="status">正在读取真题题库…</p>
      ) : failed ? (
        <p className="exam-catalog-notice" role="alert">
          暂时无法加载真题题库，请稍后重新进入本页。
        </p>
      ) : papers.length === 0 ? (
        <p className="exam-catalog-notice" role="status">
          暂无可用试卷，题库准备好后会在这里显示。
        </p>
      ) : (
        <>
          <div className="exam-catalog-summary" aria-label="真题题库概况">
            <span><strong>{papers.length}</strong> 份试卷</span>
            <span><strong>{availableCount}</strong> 道已审核题目</span>
            {excludedCount > 0 && (
              <span>{excludedCount} 道题暂不参与测试</span>
            )}
          </div>
          <div className="exam-paper-list">
            {papers.map((paper) => (
              <article className="exam-paper" key={paper.id}>
                <div className="exam-paper__meta">
                  <span>{paper.document_type === "sample_exam" ? "样题" : "历年真题"}</span>
                  <span>{paper.exam_year == null ? "年份未标注" : `${paper.exam_year} 年`}</span>
                </div>
                <h2>{paper.title}</h2>
                <p>{paper.available_question_count} 道已审核题目</p>
                {paper.question_types.length > 0 && (
                  <p className="exam-paper__types">
                    {paper.question_types
                      .map((type) => questionTypeLabels[type] ?? "其他题型")
                      .join(" · ")}
                  </p>
                )}
                {paper.excluded_question_count > 0 && (
                  <p className="exam-paper__note">
                    另有 {paper.excluded_question_count} 道题暂不参与测试。
                  </p>
                )}
                <button
                  type="button"
                  className="primary-action"
                  onClick={() => onStart(paper.id)}
                  disabled={disabled || paper.available_question_count === 0}
                  aria-label={`开始 ${paper.title} 真题测试`}
                >
                  {paper.available_question_count > 0 ? "开始真题测试" : "暂无已审核题目"}
                </button>
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
