import { CustomerLoginForm } from "@/features/auth/components/CustomerLoginForm";
import { AuthLayout } from "@/features/auth/components/AuthLayout";

export const metadata = { title: "Sign in - Support Console" };

export default function CustomerLoginPage() {
  return (
    <AuthLayout
      title="Sign in"
      description="Access your support conversations."
      eyebrow="Get help in seconds, not tickets in a queue."
      highlights={[
        "AI-assisted answers grounded in our knowledge base",
        "High-risk actions like refunds always get human approval",
        "Every conversation picks up right where you left off",
      ]}
    >
      <CustomerLoginForm />
    </AuthLayout>
  );
}
