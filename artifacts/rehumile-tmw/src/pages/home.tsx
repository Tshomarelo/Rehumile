import React from "react";
import { Link } from "wouter";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Mail, Phone, ChevronDown, Check, Activity, ShieldCheck, Database, Laptop, Terminal, Cpu, HardDrive, Wifi, MonitorSmartphone, GraduationCap, ArrowRight } from "lucide-react";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

// Assets
import logoPath from "@assets/logo_1779827846431.jpeg";
import bgPath from "@assets/web_background_1779827846433.jpeg";
import axxessLogo from "@assets/Axxess_1779827936112.png";
import microsoftLogo from "@assets/microsoft_1779827936114.png";
import pythonLogo from "@assets/pythonanywhere_1779827936115.png";
import tplinkLogo from "@assets/tplink_1779827936116.png";
import wasabiLogo from "@assets/wasbi_1779827936119.png";

const PARTNER_LOGOS = [
  { src: axxessLogo, alt: "Axxess" },
  { src: microsoftLogo, alt: "Microsoft" },
  { src: pythonLogo, alt: "PythonAnywhere" },
  { src: tplinkLogo, alt: "TP-Link" },
  { src: wasabiLogo, alt: "Wasabi" },
];

export default function Home() {
  return (
    <div className="flex flex-col min-h-screen">
      {/* Utility Top Bar */}
      <div className="bg-primary text-primary-foreground py-1 px-6 text-sm flex justify-end font-medium">
        <div className="flex items-center gap-2">
          <Phone className="h-4 w-4" />
          <span>068 397 3484</span>
        </div>
      </div>

      {/* Sticky Navigation Bar */}
      <header className="sticky top-0 z-50 w-full bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 border-b border-border shadow-sm">
        <div className="container mx-auto px-4 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <img src={logoPath} alt="Rehumile TMW Logo" className="h-10 w-auto object-contain rounded" />
          </Link>
          
          <nav className="hidden md:flex items-center gap-6 font-medium text-sm">
            <Link href="/" className="text-primary font-semibold">Home</Link>
            
            <DropdownMenu>
              <DropdownMenuTrigger className="flex items-center gap-1 hover:text-secondary transition-colors outline-none cursor-pointer">
                Services <ChevronDown className="h-3 w-3" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56">
                <DropdownMenuItem className="cursor-pointer"><Terminal className="mr-2 h-4 w-4 text-muted-foreground"/> Website Development</DropdownMenuItem>
                <DropdownMenuItem className="cursor-pointer"><Cpu className="mr-2 h-4 w-4 text-muted-foreground"/> Custom Software Development</DropdownMenuItem>
                <DropdownMenuItem className="cursor-pointer"><HardDrive className="mr-2 h-4 w-4 text-muted-foreground"/> Hardware & IT Support</DropdownMenuItem>
                <DropdownMenuItem className="cursor-pointer"><MonitorSmartphone className="mr-2 h-4 w-4 text-muted-foreground"/> Point of Sale (POS)</DropdownMenuItem>
                <DropdownMenuItem className="cursor-pointer"><ShieldCheck className="mr-2 h-4 w-4 text-muted-foreground"/> Cyber Security</DropdownMenuItem>
                <DropdownMenuItem className="cursor-pointer"><Database className="mr-2 h-4 w-4 text-muted-foreground"/> Cloud Solutions</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            <Link href="#pricing" className="hover:text-secondary transition-colors cursor-pointer">Pricing</Link>
            <Link href="#portfolio" className="hover:text-secondary transition-colors cursor-pointer">Portfolio</Link>
            <Link href="#about" className="hover:text-secondary transition-colors cursor-pointer">About Us</Link>
          </nav>

          <div className="flex items-center gap-4">
            <Button variant="outline" className="hidden md:flex text-primary border-primary hover:bg-primary/5">
              Logout (rtmw)
            </Button>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="relative w-full overflow-hidden bg-black min-h-[600px] flex items-center">
        <div className="absolute inset-0">
          <img src={bgPath} alt="Drakensberg Background" className="w-full h-full object-cover object-center opacity-40" />
          <div className="absolute inset-0 bg-gradient-to-r from-primary/90 to-black/60 mix-blend-multiply" />
        </div>
        
        <div className="relative z-10 container mx-auto px-4 md:px-6 py-24 md:py-32">
          <div className="max-w-3xl space-y-6">
            <h1 className="text-4xl md:text-5xl lg:text-6xl font-extrabold text-white leading-tight tracking-tight">
              Enterprise-Grade IT Solutions Built to <span className="text-secondary">Power Your Business</span>
            </h1>
            <p className="text-lg md:text-xl text-gray-200 leading-relaxed max-w-2xl">
              From robust network infrastructure and bulletproof cybersecurity to custom software and seamless POS systems—we manage your technology so you can focus on growth.
            </p>
            <div className="flex flex-col sm:flex-row gap-4 pt-4">
              <Button size="lg" className="bg-primary hover:bg-primary/90 text-white border border-secondary/30 shadow-lg group">
                Request a Free IT Consultation
                <ArrowRight className="ml-2 h-4 w-4 group-hover:translate-x-1 transition-transform" />
              </Button>
              <Button size="lg" variant="outline" className="bg-transparent text-white border-secondary/50 hover:bg-secondary/20 hover:text-white backdrop-blur-sm">
                Explore Our Services
              </Button>
            </div>
          </div>
        </div>
      </section>

      {/* Partner Logos Scrolling Strip */}
      <section className="bg-muted py-8 border-y border-border overflow-hidden">
        <div className="container mx-auto px-4 mb-4 text-center">
          <p className="text-sm font-semibold tracking-wider text-muted-foreground uppercase">Our Technology Partners</p>
        </div>
        <div className="flex w-full overflow-hidden">
          <div className="flex w-[fit-content] animate-marquee items-center">
            {/* First Set */}
            <div className="flex items-center space-x-12 px-6">
              {PARTNER_LOGOS.map((logo, idx) => (
                <img 
                  key={`partner-1-${idx}`} 
                  src={logo.src} 
                  alt={logo.alt} 
                  className="h-10 md:h-12 w-auto object-contain grayscale opacity-70 hover:grayscale-0 hover:opacity-100 transition-all duration-300"
                />
              ))}
            </div>
            {/* Second Set (duplicated for seamless loop) */}
            <div className="flex items-center space-x-12 px-6">
              {PARTNER_LOGOS.map((logo, idx) => (
                <img 
                  key={`partner-2-${idx}`} 
                  src={logo.src} 
                  alt={logo.alt} 
                  className="h-10 md:h-12 w-auto object-contain grayscale opacity-70 hover:grayscale-0 hover:opacity-100 transition-all duration-300"
                />
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Core Values Section */}
      <section className="py-20 bg-background" id="about">
        <div className="container mx-auto px-4">
          <div className="text-center mb-16 max-w-2xl mx-auto">
            <h2 className="text-3xl font-bold text-primary mb-4">The Pillars of Rehumile TMW</h2>
            <p className="text-muted-foreground">Built on a foundation of technical excellence, strategic foresight, and unwavering reliability.</p>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            <Card className="border-border shadow-sm hover:shadow-md transition-shadow">
              <CardHeader>
                <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                  <Activity className="h-6 w-6 text-primary" />
                </div>
                <CardTitle>Consulting</CardTitle>
              </CardHeader>
              <CardContent className="text-muted-foreground">
                Business IT alignment, Workflow Optimization, and Technology Roadmap planning.
              </CardContent>
            </Card>

            <Card className="border-border shadow-sm hover:shadow-md transition-shadow">
              <CardHeader>
                <div className="h-12 w-12 rounded-lg bg-secondary/10 flex items-center justify-center mb-4">
                  <Terminal className="h-6 w-6 text-secondary" />
                </div>
                <CardTitle>Development</CardTitle>
              </CardHeader>
              <CardContent className="text-muted-foreground">
                Custom Software Solutions, Platform and Application development.
              </CardContent>
            </Card>

            <Card className="border-border shadow-sm hover:shadow-md transition-shadow">
              <CardHeader>
                <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                  <GraduationCap className="h-6 w-6 text-primary" />
                </div>
                <CardTitle>Training</CardTitle>
              </CardHeader>
              <CardContent className="text-muted-foreground">
                Comprehensive IT Training Modules, Skill Enhancement, Staff Development.
              </CardContent>
            </Card>

            <Card className="border-border shadow-sm hover:shadow-md transition-shadow">
              <CardHeader>
                <div className="h-12 w-12 rounded-lg bg-secondary/10 flex items-center justify-center mb-4">
                  <Wifi className="h-6 w-6 text-secondary" />
                </div>
                <CardTitle>Case Studies / Community</CardTitle>
              </CardHeader>
              <CardContent className="text-muted-foreground">
                Project Studies and local engineering/development promotion initiatives.
              </CardContent>
            </Card>

            <Card className="border-border shadow-sm hover:shadow-md transition-shadow">
              <CardHeader>
                <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                  <Mail className="h-6 w-6 text-primary" />
                </div>
                <CardTitle>Communication</CardTitle>
              </CardHeader>
              <CardContent className="text-muted-foreground">
                Improved engineering and development communications systems.
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* Pricing & Services Section */}
      <section className="py-20 bg-muted" id="pricing">
        <div className="container mx-auto px-4">
          <div className="text-center mb-16 max-w-2xl mx-auto">
            <h2 className="text-3xl font-bold text-primary mb-4">Transparent Service Pricing</h2>
            <p className="text-muted-foreground">Clear, upfront costs for enterprise-grade technical support and implementation.</p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-12">
            {/* Hardware Services */}
            <Card className="border-t-4 border-t-primary shadow-md h-full flex flex-col">
              <CardHeader>
                <div className="flex items-center gap-3">
                  <Laptop className="h-6 w-6 text-primary" />
                  <CardTitle className="text-xl">Hardware & Support Services</CardTitle>
                </div>
                <CardDescription>Professional diagnostic and repair services</CardDescription>
              </CardHeader>
              <CardContent className="flex-1">
                <ul className="space-y-4">
                  <li className="flex justify-between items-start border-b border-border/50 pb-3">
                    <span className="text-sm">PC/Laptop Troubleshooting & Diagnostic Report</span>
                    <span className="font-semibold text-primary ml-4 shrink-0">R249.99</span>
                  </li>
                  <li className="flex justify-between items-start border-b border-border/50 pb-3">
                    <span className="text-sm">Virus Removal + Firmware Updates + Support Assist</span>
                    <span className="font-semibold text-primary ml-4 shrink-0">R379.99</span>
                  </li>
                  <li className="flex justify-between items-start border-b border-border/50 pb-3">
                    <span className="text-sm">Remote Assistance + Computer Health Check <span className="text-xs text-muted-foreground block">(per 30 min)</span></span>
                    <span className="font-semibold text-primary ml-4 shrink-0">R119.99</span>
                  </li>
                  <li className="flex justify-between items-start border-b border-border/50 pb-3">
                    <span className="text-sm">Local House Call / Assistance Fee <span className="text-xs text-muted-foreground block">(Excl. Services)</span></span>
                    <span className="font-semibold text-primary ml-4 shrink-0">R249.99</span>
                  </li>
                  <li className="flex justify-between items-start pt-1">
                    <span className="text-sm">Printer Installation & Maintenance</span>
                    <span className="font-semibold text-primary ml-4 shrink-0">From R299.99</span>
                  </li>
                </ul>
              </CardContent>
            </Card>

            {/* Products & Packages */}
            <Card className="border-t-4 border-t-secondary shadow-md h-full flex flex-col">
              <CardHeader>
                <div className="flex items-center gap-3">
                  <Database className="h-6 w-6 text-secondary" />
                  <CardTitle className="text-xl">Software Products</CardTitle>
                </div>
                <CardDescription>Permanent licenses and system upgrades</CardDescription>
              </CardHeader>
              <CardContent className="flex-1">
                <ul className="space-y-4">
                  <li className="flex justify-between items-start border-b border-border/50 pb-3">
                    <span className="text-sm">Latest Windows 11 OS Upgrade</span>
                    <span className="font-semibold text-primary ml-4 shrink-0">R599.99</span>
                  </li>
                  <li className="flex justify-between items-start border-b border-border/50 pb-3">
                    <span className="text-sm">Windows 10 OS Upgrade</span>
                    <span className="font-semibold text-primary ml-4 shrink-0">R479.00</span>
                  </li>
                  <li className="flex justify-between items-start border-b border-border/50 pb-3">
                    <span className="text-sm">Ms Office 365 (Latest) Permanent Subscription</span>
                    <span className="font-semibold text-primary ml-4 shrink-0">R349.99</span>
                  </li>
                  <li className="flex justify-between items-start border-b border-border/50 pb-3">
                    <span className="text-sm">Ms Office 2019 Permanent Subscription</span>
                    <span className="font-semibold text-primary ml-4 shrink-0">R299.99</span>
                  </li>
                  <li className="flex justify-between items-start pt-1">
                    <span className="text-sm">Ms Office 2016 Permanent Subscription</span>
                    <span className="font-semibold text-primary ml-4 shrink-0">R269.99</span>
                  </li>
                </ul>
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            {/* POS Services Card */}
            <Card className="shadow-md h-full flex flex-col">
              <CardHeader>
                <div className="flex items-center gap-3">
                  <MonitorSmartphone className="h-6 w-6 text-primary" />
                  <CardTitle className="text-xl">Point of Sale (POS) Solutions</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col">
                <div className="bg-secondary/10 border-l-4 border-secondary p-4 rounded-r-md mb-6">
                  <p className="text-sm text-foreground/90 font-medium">
                    <span className="text-secondary font-bold mr-1">Hardware Transparency Notice:</span> 
                    To keep your costs low, clients purchase their own hardware equipment from trusted suppliers. We provide full procurement consultation followed by expert on-site installation, software provisioning, and staff training.
                  </p>
                </div>
                
                <ul className="space-y-4">
                  <li className="flex justify-between items-start border-b border-border/50 pb-3">
                    <span className="text-sm">Basic Retail Software Provisioning <span className="text-xs text-muted-foreground block">(Single-terminal offline standalone inventory)</span></span>
                    <span className="font-semibold text-primary ml-4 shrink-0">R1 499.00</span>
                  </li>
                  <li className="flex justify-between items-start border-b border-border/50 pb-3">
                    <span className="text-sm">Hardware Peripherals Configuration <span className="text-xs text-muted-foreground block">(Printer, scanner, cash drawer setup)</span></span>
                    <span className="font-semibold text-primary ml-4 shrink-0">R699.99</span>
                  </li>
                  <li className="flex justify-between items-start border-b border-border/50 pb-3">
                    <span className="text-sm">Smart Speedpoint Integration <span className="text-xs text-muted-foreground block">(Linking independent card machines)</span></span>
                    <span className="font-semibold text-primary ml-4 shrink-0">R349.99</span>
                  </li>
                  <li className="flex justify-between items-start pt-1">
                    <span className="text-sm">On-Site Operations & Staff Training <span className="text-xs text-muted-foreground block">(Cashing up, product logging, reporting)</span></span>
                    <span className="font-semibold text-primary ml-4 shrink-0">R450.00</span>
                  </li>
                </ul>
              </CardContent>
            </Card>

            {/* Combos & Promotions */}
            <Card className="shadow-md bg-primary text-primary-foreground h-full flex flex-col border-none">
              <CardHeader>
                <div className="flex items-center gap-3">
                  <ShieldCheck className="h-6 w-6 text-secondary" />
                  <CardTitle className="text-xl">Combos & Value Packages</CardTitle>
                </div>
                <CardDescription className="text-primary-foreground/70">Bundled services for maximum value</CardDescription>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col">
                <ul className="space-y-5 flex-1">
                  <li className="flex justify-between items-start border-b border-primary-foreground/20 pb-4">
                    <div>
                      <span className="font-semibold text-secondary block mb-1">Rehumile Combo 01</span>
                      <span className="text-sm text-primary-foreground/90">Ms Office 365 Permanent + Desired Apps + Support assist + Windows/Firmware Updates</span>
                    </div>
                    <span className="font-bold text-lg ml-4 shrink-0 mt-1">R1 299.99</span>
                  </li>
                  <li className="flex justify-between items-start border-b border-primary-foreground/20 pb-4">
                    <div>
                      <span className="font-semibold text-secondary block mb-1">Rehumile Combo 02</span>
                      <span className="text-sm text-primary-foreground/90">Windows 10/11 Upgrade + Ms Office 365 Permanent + Basic Support</span>
                    </div>
                    <span className="font-bold text-lg ml-4 shrink-0 mt-1">R999.99</span>
                  </li>
                  <li className="flex justify-between items-start pb-2">
                    <div>
                      <span className="font-semibold text-secondary block mb-1">Rehumile POS Combo 03</span>
                      <span className="text-sm text-primary-foreground/90">POS Software Setup + Peripheral Configuration + Staff Training + Initial Stock Import</span>
                    </div>
                    <span className="font-bold text-lg ml-4 shrink-0 mt-1">R2 249.99</span>
                  </li>
                </ul>
                
                <div className="mt-6 bg-secondary text-secondary-foreground p-4 rounded-md text-center font-bold shadow-inner">
                  Discounted Strategic Consultation Block (5 Hrs) - Now R349.99!
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-[#2A0C10] text-gray-300 py-12 border-t-4 border-secondary">
        <div className="container mx-auto px-4 flex flex-col md:flex-row justify-between items-center gap-6 text-sm">
          <div className="flex flex-col md:flex-row items-center gap-4 text-center md:text-left">
            <span className="font-semibold text-white">CONTACT US</span>
            <span className="hidden md:inline text-secondary">•</span>
            <a href="mailto:info@rehumiletmw.co.za" className="hover:text-secondary transition-colors">info@rehumiletmw.co.za</a>
            <span className="hidden md:inline text-secondary">•</span>
            <a href="tel:+27683973484" className="hover:text-secondary transition-colors">+27 68 397 3484</a>
          </div>
          
          <div className="flex flex-col md:flex-row items-center gap-4">
            <div className="flex items-center gap-4">
              <span className="font-semibold text-white mr-2">Connect with Us</span>
              {/* Social placeholders */}
              <div className="h-8 w-8 rounded-full bg-white/10 flex items-center justify-center hover:bg-secondary hover:text-white transition-colors cursor-pointer">
                <span className="sr-only">LinkedIn</span>
                in
              </div>
              <div className="h-8 w-8 rounded-full bg-white/10 flex items-center justify-center hover:bg-secondary hover:text-white transition-colors cursor-pointer">
                <span className="sr-only">Twitter</span>
                𝕏
              </div>
            </div>
            <div className="mt-4 md:mt-0 text-gray-500">
              © 2026 Rehumile TMW. All rights reserved.
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
