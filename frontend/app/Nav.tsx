import Link from "next/link";

// Slim sticky top bar shared across every route (rendered once in the root
// layout). Pure next/link markup — no hooks, no fetches — so it stays a server
// component, adds zero client JS, and can't touch the Ask stream.
export default function Nav() {
  return (
    <nav className="nav">
      <div className="nav-inner">
        <Link href="/" className="nav-brand">
          civicscope
        </Link>
        <div className="nav-links">
          <Link href="/browse">Browse</Link>
          <Link href="/analytics">Analytics</Link>
          <Link href="/about">About</Link>
        </div>
      </div>
    </nav>
  );
}
