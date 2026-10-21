import { DashboardSource } from "~/.server/dashboard-source";
import { DraftSegmenter } from "~/.server/draft-segmenter";
import { FixtureLog } from "~/.server/fixture-log";
import { FixtureTutorApi } from "~/.server/fixture-tutor-api";
import { TurnProjection } from "~/.server/turn-projection";
import { HttpTutorApi, type TutorApi } from "~/.server/tutor-api";

export type DashboardEnv = {
  TUTOR_API_MODE?: string;
  TUTOR_API_URL?: string;
  TUTOR_ID?: string;
};

/**
 * The one place server-side collaborators are constructed. A loader asks it
 * for a `DashboardSource`; nothing below constructs its own collaborators.
 */
export class CompositionRoot {
  constructor(
    private readonly env: DashboardEnv = process.env,
    private readonly fixtureLog: FixtureLog = FixtureLog.empty(),
  ) {}

  dashboardSource(): DashboardSource {
    return new DashboardSource(
      this.tutorApi(),
      new TurnProjection(new DraftSegmenter()),
    );
  }

  tutorId(): string {
    const tutorId = this.env.TUTOR_ID ?? "tutor";
    if (!tutorId.trim()) {
      throw new Error("TUTOR_ID is empty.");
    }
    return tutorId;
  }

  private tutorApi(): TutorApi {
    const mode = this.env.TUTOR_API_MODE ?? "fixture";
    if (mode === "fixture") {
      return new FixtureTutorApi(this.fixtureLog);
    }
    if (mode === "live") {
      return new HttpTutorApi(
        this.env.TUTOR_API_URL ?? "http://127.0.0.1:8000",
      );
    }
    throw new Error(
      `TUTOR_API_MODE must be "fixture" or "live", not "${mode}".`,
    );
  }
}
