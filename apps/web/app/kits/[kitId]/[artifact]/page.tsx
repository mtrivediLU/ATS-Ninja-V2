import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ArtifactRoute } from "@/components/product/artifact-route";
import { KitStateBoundary } from "@/components/product/kit-state";
import { artifactSlugs, type ArtifactSlug } from "@/lib/navigation";

export async function generateMetadata({ params }: { params: Promise<{ artifact: string }> }): Promise<Metadata> {
  const { artifact } = await params;
  return { title: artifact.replaceAll("-", " ") };
}

export default async function KitArtifactPage({ params }: { params: Promise<{ artifact: string }> }) {
  const { artifact } = await params;
  if (!artifactSlugs.includes(artifact as ArtifactSlug)) notFound();
  return <KitStateBoundary><ArtifactRoute artifact={artifact as ArtifactSlug} /></KitStateBoundary>;
}
