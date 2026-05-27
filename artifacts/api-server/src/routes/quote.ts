import { Router } from "express";
import nodemailer from "nodemailer";

const router = Router();

const transporter = nodemailer.createTransport({
  host: process.env.EMAIL_HOST || "mail.rehumile.co.za",
  port: 587,
  secure: false,
  auth: {
    user: process.env.EMAIL_HOST_USER,
    pass: process.env.EMAIL_HOST_PASSWORD,
  },
  tls: { rejectUnauthorized: false },
});

router.post("/quote", async (req, res) => {
  const { name, email, phone, company, service, message } = req.body as {
    name?: string;
    email?: string;
    phone?: string;
    company?: string;
    service?: string;
    message?: string;
  };

  if (!name || !email || !message) {
    res.status(400).json({ error: "Name, email and message are required." });
    return;
  }

  const serviceLabel = service || "General Enquiry";

  const html = `
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:32px 0">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)">
        <tr>
          <td style="background:#50181E;padding:28px 32px">
            <h1 style="margin:0;color:#B38F43;font-size:22px;font-weight:700;letter-spacing:1px">REHUMILE TMW</h1>
            <p style="margin:4px 0 0;color:#ffffff;font-size:13px;opacity:0.8">New Quote Request Received</p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="padding-bottom:16px;border-bottom:1px solid #eee">
                  <p style="margin:0;font-size:13px;color:#888">Full Name</p>
                  <p style="margin:4px 0 0;font-size:16px;color:#222;font-weight:600">${name}</p>
                </td>
              </tr>
              <tr>
                <td style="padding:16px 0;border-bottom:1px solid #eee">
                  <p style="margin:0;font-size:13px;color:#888">Email Address</p>
                  <p style="margin:4px 0 0;font-size:15px;color:#222"><a href="mailto:${email}" style="color:#50181E">${email}</a></p>
                </td>
              </tr>
              ${phone ? `
              <tr>
                <td style="padding:16px 0;border-bottom:1px solid #eee">
                  <p style="margin:0;font-size:13px;color:#888">Phone Number</p>
                  <p style="margin:4px 0 0;font-size:15px;color:#222">${phone}</p>
                </td>
              </tr>` : ""}
              ${company ? `
              <tr>
                <td style="padding:16px 0;border-bottom:1px solid #eee">
                  <p style="margin:0;font-size:13px;color:#888">Company / Organisation</p>
                  <p style="margin:4px 0 0;font-size:15px;color:#222">${company}</p>
                </td>
              </tr>` : ""}
              <tr>
                <td style="padding:16px 0;border-bottom:1px solid #eee">
                  <p style="margin:0;font-size:13px;color:#888">Service Required</p>
                  <p style="margin:4px 0 0;font-size:15px;color:#50181E;font-weight:600">${serviceLabel}</p>
                </td>
              </tr>
              <tr>
                <td style="padding:16px 0">
                  <p style="margin:0;font-size:13px;color:#888">Message / Requirements</p>
                  <p style="margin:8px 0 0;font-size:15px;color:#333;line-height:1.6;background:#fafafa;padding:12px;border-left:3px solid #B38F43;border-radius:2px">${message.replace(/\n/g, "<br>")}</p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <tr>
          <td style="background:#f9f9f9;padding:16px 32px;border-top:1px solid #eee">
            <p style="margin:0;font-size:12px;color:#aaa;text-align:center">This enquiry was submitted via the Rehumile TMW website contact form.</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>`;

  try {
    await transporter.sendMail({
      from: `"Rehumile TMW Website" <${process.env.EMAIL_HOST_USER || "noreply@rehumile.co.za"}>`,
      to: "infor@rehumile.co.za",
      replyTo: email,
      subject: `Quote Request: ${serviceLabel} — ${name}`,
      html,
    });

    await transporter.sendMail({
      from: `"Rehumile TMW" <${process.env.EMAIL_HOST_USER || "noreply@rehumile.co.za"}>`,
      to: email,
      subject: "We received your quote request — Rehumile TMW",
      html: `
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:32px 0">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)">
        <tr><td style="background:#50181E;padding:28px 32px">
          <h1 style="margin:0;color:#B38F43;font-size:22px;font-weight:700">REHUMILE TMW</h1>
          <p style="margin:4px 0 0;color:#fff;font-size:13px;opacity:0.8">Quote Request Confirmation</p>
        </td></tr>
        <tr><td style="padding:32px">
          <p style="font-size:15px;color:#333">Hi <strong>${name}</strong>,</p>
          <p style="font-size:15px;color:#333;line-height:1.7">Thank you for reaching out to <strong>Rehumile TMW</strong>. We have received your quote request for <strong style="color:#50181E">${serviceLabel}</strong> and one of our consultants will be in touch with you shortly.</p>
          <p style="font-size:15px;color:#333;line-height:1.7">In the meantime, feel free to call us on <strong>068 397 3484</strong> or email <a href="mailto:info@rehumile.co.za" style="color:#50181E">info@rehumile.co.za</a> if your request is urgent.</p>
          <p style="font-size:14px;color:#888;margin-top:24px">Warm regards,<br><strong style="color:#50181E">The Rehumile TMW Team</strong></p>
        </td></tr>
        <tr><td style="background:#f9f9f9;padding:16px 32px;border-top:1px solid #eee">
          <p style="margin:0;font-size:12px;color:#aaa;text-align:center">© 2026 Rehumile TMW · Jozini, KwaZulu-Natal, South Africa</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>`,
    });

    res.json({ success: true });
  } catch (err) {
    req.log.error(err, "Failed to send quote request email");
    res.status(500).json({ error: "Failed to send message. Please try again or email us directly." });
  }
});

export default router;
