import PolicyShell, { Section } from "../components/PolicyShell";

export default function Cookies() {
  return (
    <PolicyShell title="Cookie Policy" updated="12 July 2026">
      <p>
        This demo uses minimal browser storage. This policy explains what is stored
        and how your consent is recorded.
      </p>

      <Section heading="Strictly necessary">
        <ul className="list-inside list-disc space-y-1">
          <li><span className="font-medium text-navy">Authentication token</span> —
            stored in your browser's local storage to keep you signed in. Required for
            the app to function; cannot be disabled while signed in.</li>
          <li><span className="font-medium text-navy">Consent flag</span> — remembers
            your cookie choice so we don't ask again.</li>
        </ul>
      </Section>

      <Section heading="Analytics (optional)">
        <p>
          If you accept analytics in the consent banner, we record that preference.
          This demo does not load any third-party analytics or advertising trackers —
          the toggle exists to demonstrate consent tracking.
        </p>
      </Section>

      <Section heading="How consent is tracked">
        <p>
          When you accept or decline, we send a consent record (the policy, its
          version, your choice, a timestamp, and your user agent) to our backend so we
          have an auditable log. You can change your mind by clearing the site's local
          storage, which will bring the banner back.
        </p>
      </Section>
    </PolicyShell>
  );
}
