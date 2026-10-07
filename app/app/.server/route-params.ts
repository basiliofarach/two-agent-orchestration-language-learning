const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Route parameters are checked before they reach a backend path. Every id the
 * dashboard routes on is a UUID; anything else is a page that does not exist.
 */
export class RouteParams {
  constructor(
    private readonly params: Readonly<Record<string, string | undefined>>,
  ) {}

  uuid(name: string, resource: string): string {
    const value = this.params[name];
    if (value === undefined || !UUID.test(value)) {
      throw new Response(`${resource} not found`, { status: 404 });
    }
    return value;
  }
}
