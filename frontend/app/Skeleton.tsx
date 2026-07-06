// Shimmer placeholders shown while a page fetches its main content. Purely
// decorative, so it's hidden from assistive tech — the surrounding region
// carries an aria-busy/label for that.
export function Skeleton({
  lines = 4,
  title = false,
}: {
  lines?: number;
  title?: boolean;
}) {
  return (
    <div aria-hidden="true">
      {title && <div className="skeleton skeleton-title" />}
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="skeleton skeleton-line"
          style={{ width: i === lines - 1 ? "55%" : "100%" }}
        />
      ))}
    </div>
  );
}

// A skeleton wrapped in the standard panel, for full-page loading states.
export function PanelSkeleton({
  lines = 5,
  label = "Loading",
}: {
  lines?: number;
  label?: string;
}) {
  return (
    <div className="panel" role="status" aria-busy="true" aria-label={label}>
      <Skeleton lines={lines} title />
    </div>
  );
}
