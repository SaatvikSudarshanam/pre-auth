// Separate token stores for the two role trees. A customer token and an admin
// token never share a slot, so switching roles in one browser is clean.
const CUST = "claims_customer_token";
const ADMIN = "claims_admin_token";

export const getCustomerToken = () => localStorage.getItem(CUST);
export const setCustomerToken = (t) => localStorage.setItem(CUST, t);
export const clearCustomerToken = () => localStorage.removeItem(CUST);

export const getAdminToken = () => localStorage.getItem(ADMIN);
export const setAdminToken = (t) => localStorage.setItem(ADMIN, t);
export const clearAdminToken = () => localStorage.removeItem(ADMIN);
