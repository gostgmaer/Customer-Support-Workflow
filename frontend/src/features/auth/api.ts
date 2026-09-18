import { apiFetch } from "@/lib/api/client";
import type { CustomerAuthResponse, CustomerMe, StaffLoginResponse } from "@/types/api";

import type { CustomerLoginInput, CustomerRegisterInput, StaffLoginInput } from "./schemas";

export function customerRegister(input: CustomerRegisterInput) {
  return apiFetch<CustomerAuthResponse>("/api/v1/customers/register", {
    method: "POST",
    body: input,
    anonymous: true,
  });
}

export function customerLogin(input: CustomerLoginInput) {
  return apiFetch<CustomerAuthResponse>("/api/v1/customers/login", {
    method: "POST",
    body: input,
    anonymous: true,
  });
}

export function fetchCustomerMe() {
  return apiFetch<CustomerMe>("/api/v1/customers/me");
}

export function staffLogin(input: StaffLoginInput) {
  return apiFetch<StaffLoginResponse>("/api/v1/staff/login", {
    method: "POST",
    body: input,
    anonymous: true,
  });
}
