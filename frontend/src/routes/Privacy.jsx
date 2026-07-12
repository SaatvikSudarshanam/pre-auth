import PolicyShell, { Section } from "../components/PolicyShell";

export default function Privacy() {
  return (
    <PolicyShell title="Privacy Policy" updated="12 July 2026">
      <p>
        This is a demonstration application. This policy explains what data PreAuthIQ
        processes and why. It is written for the demo and is not legal advice.
      </p>

      <Section heading="Data we collect">
        <ul className="list-inside list-disc space-y-1">
          <li>Account details: your email address, and — if you sign in with Google —
            your name and profile picture from your Google account.</li>
          <li>Profile details you provide: full name, date of birth, and selected plan.</li>
          <li>Claim data: pre-authorization requests and the documents you upload
            (e.g. prescriptions, itemized bills, discharge summaries).</li>
          <li>Consent records: your cookie and privacy choices, with a timestamp.</li>
        </ul>
      </Section>

      <Section heading="How we use it">
        <p>
          To operate the pre-authorization workflow: registering requests, checking
          document completeness, verifying coverage against your plan, producing an
          advisory AI assessment for a human reviewer, and communicating decisions.
        </p>
      </Section>

      <Section heading="AI processing">
        <p>
          On the reviewer (admin) side only, claim details, extracted document text,
          and your plan rules are sent to a third-party large-language-model (LLM)
          provider to generate an advisory assessment. A human reviewer makes the
          final decision. The customer app does not send your data to any AI provider.
          The specific subprocessor is disclosed in our reviewer documentation.
        </p>
      </Section>

      <Section heading="Sharing & retention">
        <p>
          We do not sell your data. Claims and AI reviews are retained for audit and
          are not deleted in this demo. In production, retention would follow
          applicable regulatory requirements.
        </p>
      </Section>

      <Section heading="Your choices">
        <p>
          You can manage cookie preferences via the consent banner. For a real
          deployment you would also have rights to access, correct, or delete your
          data, subject to legal retention obligations.
        </p>
      </Section>

      <Section heading="Contact">
        <p>Demo only — no contact address is provided.</p>
      </Section>
    </PolicyShell>
  );
}
