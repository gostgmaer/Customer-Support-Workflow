import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { useAuthStore } from "@/store/auth-store";
import { toast } from "@/store/toast-store";

import { customerLogin, customerRegister, staffLogin } from "./api";
import type { CustomerLoginInput, CustomerRegisterInput, StaffLoginInput } from "./schemas";

export function useSession() {
  return useAuthStore((state) => state.session);
}

export function useLogout() {
  const logout = useAuthStore((state) => state.logout);
  const router = useRouter();
  return () => {
    logout();
    router.push("/login");
  };
}

export function useCustomerLogin() {
  const setSession = useAuthStore((state) => state.setSession);
  const router = useRouter();

  return useMutation({
    mutationFn: (input: CustomerLoginInput) => customerLogin(input),
    onSuccess: (data) => {
      setSession({ scope: "customer", token: data.access_token, id: data.customer_id, name: data.full_name });
      toast.success(`Welcome back, ${data.full_name.split(" ")[0]}`);
      router.push("/chat");
    },
  });
}

export function useCustomerRegister() {
  const setSession = useAuthStore((state) => state.setSession);
  const router = useRouter();

  return useMutation({
    mutationFn: (input: CustomerRegisterInput) => customerRegister(input),
    onSuccess: (data) => {
      setSession({ scope: "customer", token: data.access_token, id: data.customer_id, name: data.full_name });
      toast.success(`Welcome, ${data.full_name.split(" ")[0]}`, "Your account has been created.");
      router.push("/chat");
    },
  });
}

export function useStaffLogin() {
  const setSession = useAuthStore((state) => state.setSession);
  const router = useRouter();

  return useMutation({
    mutationFn: (input: StaffLoginInput) => staffLogin(input),
    onSuccess: (data, variables) => {
      setSession({ scope: "staff", token: data.access_token, id: variables.username, role: data.role });
      toast.success("Signed in");
      router.push("/dashboard");
    },
  });
}
