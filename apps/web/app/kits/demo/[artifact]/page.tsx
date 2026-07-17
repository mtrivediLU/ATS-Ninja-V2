import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ArtifactFoundation } from "@/components/foundation/artifact-foundation";
import { artifactSlugs, type ArtifactSlug } from "@/lib/navigation";

export function generateStaticParams() {
  return artifactSlugs.map((artifact) => ({ artifact }));
}

export async function generateMetadata({ params }: { params: Promise<{ artifact: string }> }): Promise<Metadata> {
  const { artifact } = await params;
  return { title: artifact.replaceAll("-", " ") };
}

export default async function DemoArtifactPage({ params }: { params: Promise<{ artifact: string }> }) {
  const { artifact } = await params;
  if (!artifactSlugs.includes(artifact as ArtifactSlug)) notFound();
  return <ArtifactFoundation artifact={artifact as ArtifactSlug} />;
}
