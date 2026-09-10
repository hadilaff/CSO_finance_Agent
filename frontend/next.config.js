/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow the frontend to call the Lightsail backend from server components
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
