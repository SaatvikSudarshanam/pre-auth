import emailjs from "@emailjs/browser";

const SERVICE_ID = import.meta.env.VITE_EMAILJS_SERVICE_ID;
const TEMPLATE_ID = import.meta.env.VITE_EMAILJS_TEMPLATE_ID;
const PUBLIC_KEY = import.meta.env.VITE_EMAILJS_PUBLIC_KEY;

const ACTION_LABELS = {
  approved: "Approved",
  rejected: "Rejected",
  requested_info: "More Information Needed",
};

export function isEmailConfigured() {
  return Boolean(SERVICE_ID && TEMPLATE_ID && PUBLIC_KEY);
}

/**
 * Send a decision notification email to the customer via EmailJS.
 * Template variables must match your EmailJS template (see README / setup guide).
 */
export async function sendDecisionEmail({ toEmail, toName, claimId, action, message, claimType }) {
  if (!isEmailConfigured()) {
    throw new Error("EmailJS is not configured. Add VITE_EMAILJS_* variables to frontend/.env");
  }

  return emailjs.send(
    SERVICE_ID,
    TEMPLATE_ID,
    {
      to_email: toEmail,
      name: toName || toEmail,
      time: new Date().toLocaleString("en-IN", {
        dateStyle: "medium",
        timeStyle: "short",
      }),
      message,
      claim_id: String(claimId),
      decision: ACTION_LABELS[action] || action,
      claim_type: claimType || "",
    },
    PUBLIC_KEY,
  );
}
