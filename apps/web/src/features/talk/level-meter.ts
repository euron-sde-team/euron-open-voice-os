/**
 * Audio level (0 to 1) of a media track, sampled ten times a second with a Web Audio
 * analyser. Pipecat's local media manager reports no levels of its own, and the Talk page
 * needs them: for the orb, and to time an answer from when the caller really went quiet.
 */
export function meterTrack(track: MediaStreamTrack, onLevel: (level: number) => void, everyMs = 100): () => void {
  const context = new AudioContext();
  const source = context.createMediaStreamSource(new MediaStream([track]));
  const analyser = context.createAnalyser();
  analyser.fftSize = 512;
  source.connect(analyser);
  const samples = new Float32Array(analyser.fftSize);
  const timer = window.setInterval(() => {
    analyser.getFloatTimeDomainData(samples);
    onLevel(rmsLevel(samples));
  }, everyMs);
  return () => {
    window.clearInterval(timer);
    source.disconnect();
    void context.close().catch(() => undefined);
  };
}

/** Root mean square of the samples, scaled so ordinary speech lands between 0.1 and 1. */
export function rmsLevel(samples: Float32Array): number {
  let sum = 0;
  for (const s of samples) sum += s * s;
  const rms = Math.sqrt(sum / Math.max(1, samples.length));
  return Math.min(1, rms * 4);
}
