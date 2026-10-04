"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Bell, Bookmark, CalendarDays, Check, ChevronRight, CircleAlert, Clock3, Menu, Sparkles, Target } from "lucide-react";
import styles from "./v2.module.css";

const recommendations = [
  { title: "Cultural safety in everyday practice", detail: "Online · 45 min · Category E", points: "1 pt" },
  { title: "Leading a safer primary-care team", detail: "Hybrid · 2 hrs · Category D", points: "2 pts" },
  { title: "Women’s health update", detail: "Auckland · 18 May · Category A", points: "3 pts" },
];

export default function RenewalCommandCenter() {
  const [saved, setSaved] = useState(false);
  const [focused, setFocused] = useState(false);

  return (
    <main className={styles.page}>
      <aside className={styles.sidebar}>
        <Link href="/" className={styles.brand}><span>+</span> Care Credits</Link>
        <p className={styles.navLabel}>APC 2026</p>
        <nav>
          <a className={styles.active} href="#overview"><Target /> Renewal plan</a>
          <a href="#runway"><CalendarDays /> Renewal runway</a>
          <a href="#learn"><Sparkles /> Find learning</a>
          <a href="#activity"><Clock3 /> Activity</a>
        </nav>
        <div className={styles.sidebarFooter}><small>Signed in as</small><strong>Dr. Sarah Chen</strong><span>General Practice</span></div>
      </aside>

      <section className={styles.content} id="overview">
        <header className={styles.topbar}>
          <button className={styles.menu} aria-label="Open menu"><Menu /></button>
          <div><p>Sunday, 13 May</p><h1>Your renewal command center</h1></div>
          <div className={styles.actions}><Link href="/v1">View V1</Link><button aria-label="Notifications"><Bell /></button><span>SC</span></div>
        </header>

        <section className={styles.status}>
          <div><p className={styles.kicker}><i /> On track for renewal</p><h2>You’re 8 points away from a complete APC.</h2><p className={styles.statusCopy}>You have time. Focus on two missing categories and your renewal will be ready before 30 June.</p></div>
          <div className={styles.score}><strong>92<span>%</span></strong><small>predicted<br />readiness</small></div>
        </section>

        <section className={styles.primaryCard}>
          <div className={styles.primaryIcon}><Sparkles /></div>
          <div className={styles.primaryCopy}><p>YOUR NEXT BEST ACTION</p><h2>Close your Cultural Safety gap this week.</h2><span>Take a 45-minute online module to earn your final Category E point.</span><div><b>45 min</b><b>Online</b><b>+1 Category E point</b></div></div>
          <div className={styles.primaryActions}><button onClick={() => setFocused(!focused)}>{focused ? <><Check /> Added to plan</> : <>Focus on this <ArrowRight /></>}</button><button className={styles.save} onClick={() => setSaved(!saved)} aria-label="Save recommendation"><Bookmark fill={saved ? "currentColor" : "none"} /></button></div>
        </section>

        <div className={styles.grid}>
          <section className={styles.card} id="runway">
            <div className={styles.cardHeading}><div><p className={styles.sectionEyebrow}>Your plan</p><h2>Renewal runway</h2></div><span>48 days left</span></div>
            <ol className={styles.runway}>
              <li className={styles.done}><i><Check /></i><div><strong>12 points recorded</strong><span>Current progress</span></div><em>Today</em></li>
              <li className={focused ? styles.current : ""}><i>{focused ? <Check /> : "2"}</i><div><strong>Complete Cultural Safety</strong><span>Earn 1 Category E point</span></div><em>This week</em></li>
              <li><i>3</i><div><strong>Join a leadership activity</strong><span>Earn 2–3 Category D points</span></div><em>By 15 Jun</em></li>
              <li><i>4</i><div><strong>Submit APC renewal</strong><span>Review certificates and submit</span></div><em>30 Jun</em></li>
            </ol>
          </section>

          <section className={styles.card} id="activity">
            <div className={styles.cardHeading}><div><p className={styles.sectionEyebrow}>At a glance</p><h2>Keep an eye on</h2></div></div>
            <div className={styles.metrics}><article><strong>12<span>/20</span></strong><p>points earned</p></article><article><strong>2</strong><p>categories to close</p></article></div>
            <div className={styles.alert}><CircleAlert /><p><b>Action needed</b><br />Leadership requires at least 2 more points.</p></div>
            <Link href="/v1" className={styles.textLink}>See detailed category view <ChevronRight /></Link>
          </section>
        </div>

        <section className={styles.card} id="learn">
          <div className={styles.cardHeading}><div><p className={styles.sectionEyebrow}>Recommended for your plan</p><h2>Learning that moves you forward</h2></div><button>Browse all <ChevronRight /></button></div>
          <div className={styles.recommendations}>{recommendations.map((item, index) => <article key={item.title}><span className={styles.recNumber}>0{index + 1}</span><div><h3>{item.title}</h3><p>{item.detail}</p></div><b>{item.points}</b><button aria-label={`Open ${item.title}`}><ChevronRight /></button></article>)}</div>
        </section>
      </section>
    </main>
  );
}
