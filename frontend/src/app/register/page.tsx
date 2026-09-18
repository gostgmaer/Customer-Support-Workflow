import { CustomerRegisterForm } from "@/features/auth/components/CustomerRegisterForm";
import { AuthLayout } from "@/features/auth/components/AuthLayout";

export const metadata = { title: "Create account - Support Console" };

export default function RegisterPage() {
  return (
    <AuthLayout
      title="Create your account"
      description="Start a conversation with our support team."
      eyebrow="One account, every conversation."
      highlights={[
        "Free to create, no setup required",
        "Ask about orders, refunds, subscriptions, and more",
        "Your history is saved for next time",
      ]}
    >
      <CustomerRegisterForm />
    </AuthLayout>
  );
}
