export const maskPhone = (value: string | null | undefined) => value ? `••••${value.slice(-4)}` : "No phone mapped";
