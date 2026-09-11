import os
import sys
import argparse
import glob
from PIL import Image, ImageDraw
import json

def draw_boxes(image, boxes, color="red"): #dessin des bbox
    draw = ImageDraw.Draw(image)
    w, h = image.size
    
    box_thick = max(1, w // 1000)
    for box in boxes:
        x1, y1, x2, y2 = box
        for i in range(box_thick):
            draw.rectangle([x1 - i, y1 - i, x2 + i, y2 + i], outline=color)
    return image

def main():
    #mode Snakemake
    if 'snakemake' in globals():
        frames_dir = snakemake.params.frames_path
        detections_dir = snakemake.params.detections_path
        output_dir = snakemake.params.output_path
    else:
        #mode ligne de commande
        parser = argparse.ArgumentParser(description='Annotate frames with detection boxes')
        parser.add_argument('--frames', required=True, dest='frames_dir')
        parser.add_argument('--detections', required=True, dest='detections_dir')
        parser.add_argument('--output', required=True, dest='output_dir')
        args = parser.parse_args()
        frames_dir = args.frames_dir
        detections_dir = args.detections_dir
        output_dir = args.output_dir

    #dossier de sortie
    os.makedirs(output_dir, exist_ok=True)
    
    #liste de toutes les frames originales
    frame_files = glob.glob(os.path.join(frames_dir, '*.jpg'))
    
    for frame_path in frame_files:
        frame_name = os.path.basename(frame_path)
        frame_id = os.path.splitext(frame_name)[0]
        
        #chargement
        img = Image.open(frame_path)
        
        #trouver les détections correspondantes
        detection_files = glob.glob(os.path.join(detections_dir, f'{frame_id}_*.jpg'))
        boxes = []
        
        for detection in detection_files:
            #extraction des coordonnées du nom de fichier
            base_name = os.path.splitext(os.path.basename(detection))[0]
            parts = base_name.split('_')
            
            #format : [frame_id]_[x1]_[y1]_[x2]_[y2]
            if len(parts) < 5:
                continue
            try:
                #donc 4 derniers éléments --> coordonnées
                coords = parts[-4:]
                x1, y1, x2, y2 = map(int, coords)
                boxes.append((x1, y1, x2, y2))
            except (ValueError, IndexError):
                continue
        
        #dessiner les boîtes si des détections existent
        if boxes:
            img = draw_boxes(img, boxes)
        
        #sauvegarde de l'image annotée
        img.save(os.path.join(output_dir, frame_name))

if __name__ == '__main__':
    main()
