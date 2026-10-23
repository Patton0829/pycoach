export function DifficultyStars({ difficulty }: { difficulty: number }) {
  if (!Number.isInteger(difficulty) || difficulty < 1 || difficulty > 5) {
    return null;
  }

  const label = `难度 ${difficulty} 星，共 5 星`;
  return (
    <span className="difficulty-stars" role="img" aria-label={label} title={label}>
      {[1, 2, 3, 4, 5].map((level) => (
        <span
          key={level}
          className={`difficulty-stars__star${level <= difficulty ? " difficulty-stars__star--active" : ""}`}
          aria-hidden="true"
        >
          ★
        </span>
      ))}
    </span>
  );
}
