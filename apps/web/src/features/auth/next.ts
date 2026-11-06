/** `?next=` target after login / password change: same-site paths only ("//host" and "/\host" leave the site),
 * never back to the login or password page. */
export function safeNext(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return "/";
  if (raw.startsWith("/login") || raw.startsWith("/password")) return "/";
  return raw;
}
