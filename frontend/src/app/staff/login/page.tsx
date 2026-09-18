import { StaffLoginForm } from "@/features/auth/components/StaffLoginForm";
import { AuthLayout } from "@/features/auth/components/AuthLayout";

export const metadata = { title: "Staff sign in - Support Console" };

export default function StaffLoginPage() {
  return (
    <AuthLayout
      title="Staff sign in"
      description="Sign in to review and act on the ticket queue."
      eyebrow="One queue, scoped to your role."
      highlights={[
        "Security, fraud, and legal tickets route to the right team automatically",
        "Approve or reject high-risk actions with a full audit trail",
        "Connect JIRA, email, and WooCommerce - no code required",
      ]}
    >
      <StaffLoginForm />
    </AuthLayout>
  );
}
