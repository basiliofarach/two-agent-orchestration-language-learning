/** A tutor action the backend will not log (REQ-DASH). */
export class ActionRejected extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "ActionRejected";
  }
}
