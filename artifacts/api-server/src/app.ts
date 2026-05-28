import express, { type Express } from "express";
import cors from "cors";
import pinoHttp from "pino-http";
import { createProxyMiddleware } from "http-proxy-middleware";
import router from "./routes";
import { logger } from "./lib/logger";

const app: Express = express();

app.use(
  pinoHttp({
    logger,
    serializers: {
      req(req) {
        return {
          id: req.id,
          method: req.method,
          url: req.url?.split("?")[0],
        };
      },
      res(res) {
        return {
          statusCode: res.statusCode,
        };
      },
    },
  }),
);
app.use(cors());

// Proxy /portal requests to Django BEFORE body parsers
// (proxy-middleware must see the raw stream)
app.use(
  "/portal",
  createProxyMiddleware({
    target: "http://localhost:8000",
    changeOrigin: true,
    logger: console,
  }),
);

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Express-side API routes (healthz, quote fallback for dev)
app.use("/api", router);

// Catch-all: proxy the main website, static files, and everything else to Django
app.use(
  "/",
  createProxyMiddleware({
    target: "http://localhost:8000",
    changeOrigin: true,
  }),
);

export default app;
