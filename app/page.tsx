import Link from "next/link";
import styles from "./home.module.css";

const versions = [
  {
    href: "/v1",
    number: "01",
    name: "Dashboard V1",
    eyebrow: "Current experience",
    description:
      "The original CPD dashboard — a detailed, data-rich overview of points, categories, events, and recommendations.",
    tags: ["Category breakdown", "Event feed", "Compliance score"],
  },
  {
    href: "/v2",
    number: "02",
    name: "Dashboard V2",
    eyebrow: "Renewal command center",
    description:
      "A focused renewal co-pilot that makes the next best action, compliance gaps, and deadline plan immediately clear.",
    tags: ["Next best action", "Renewal runway", "Priority gaps"],
  },
  {
    href: "/v3",
    number: "03",
    name: "Dashboard V3",
    eyebrow: "Renewal planner",
    description:
      "A calendar-led plan that turns APC renewal into a clear schedule of learning, milestones, and quick wins.",
    tags: ["APC calendar", "Next-up module", "Milestone rail"],
  },
  {
    href: "/v4",
    number: "04",
    name: "Dashboard V4",
    eyebrow: "Progress navigator",
    description:
      "A guided renewal pathway that replaces dashboard noise with a clear stage, useful progress, and one meaningful next move.",
    tags: ["Renewal pathway", "Focus action", "Progress health"],
  },
];

export default function VersionPicker() {
  return (
    <main className={styles.page}>
      <div className={styles.glow} />
      <header className={styles.header}>
        <Link href="/" className={styles.brand}>
          <span className={styles.mark}>+</span>
          <span>Care Credits</span>
        </Link>
        <span className={styles.badge}>Product explorations</span>
      </header>

      <section className={styles.intro}>
        <p>APC renewal, made calmer</p>
        <h1>Choose a dashboard direction.</h1>
        <span>
          Compare a detailed overview, a decisive command center, a calendar-led
          renewal plan, and a guided renewal pathway.
        </span>
      </section>

      <section className={styles.cards} aria-label="Dashboard versions">
        {versions.map((version) => (
          <Link href={version.href} className={styles.card} key={version.href}>
            <div className={styles.cardTop}>
              <span>{version.number}</span>
              <span className={styles.open}>Open dashboard ↗</span>
            </div>
            <p className={styles.eyebrow}>{version.eyebrow}</p>
            <h2>{version.name}</h2>
            <p className={styles.description}>{version.description}</p>
            <div className={styles.preview} data-version={version.number}>
              <i />
              <i />
              <i />
              <b />
              <b />
            </div>
            <ul>
              {version.tags.map((tag) => (
                <li key={tag}>{tag}</li>
              ))}
            </ul>
          </Link>
        ))}
      </section>
    </main>
  );
}
