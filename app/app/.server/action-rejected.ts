/** A tutor action the backend will not log (REQ-DASH). */
export class ActionRejected extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ActionRejected";
  }
}
