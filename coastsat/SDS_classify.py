"""This module contains functions to label satellite images and train the CoastSat classifier

   Author: Kilian Vos, Water Research Laboratory, University of New South Wales
"""

# load modules
import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import pdb
import pickle
import warnings
warnings.filterwarnings("ignore")
from matplotlib.widgets import LassoSelector
from matplotlib import path

# image processing modules
from skimage.segmentation import flood
from pylab import ginput
from sklearn.metrics import confusion_matrix
np.set_printoptions(precision=2)

# CoastSat functions
from coastsat import SDS_download, SDS_preprocess, SDS_shoreline, SDS_tools, SDS_transects

class SelectFromImage(object):
    # initialize lasso selection class
    def __init__(self, ax, implot, color=[1,1,1]):
        self.canvas = ax.figure.canvas
        self.implot = implot
        self.array = implot.get_array()
        xv, yv = np.meshgrid(np.arange(self.array.shape[1]),np.arange(self.array.shape[0]))
        self.pix = np.vstack( (xv.flatten(), yv.flatten()) ).T
        self.ind = []
        self.im_bool = np.zeros((self.array.shape[0], self.array.shape[1]))
        self.color = color
        self.lasso = LassoSelector(ax, onselect=self.onselect)

    def onselect(self, verts):
        # find pixels contained in the lasso
        p = path.Path(verts)
        self.ind = p.contains_points(self.pix, radius=1)
        # color selected pixels
        array_list = []
        for k in range(self.array.shape[2]):
            array2d = self.array[:,:,k]    
            lin = np.arange(array2d.size)
            new_array2d = array2d.flatten()
            new_array2d[lin[self.ind]] = self.color[k]
            array_list.append(new_array2d.reshape(array2d.shape))
        self.array = np.stack(array_list,axis=2)
        self.implot.set_data(self.array)
        self.canvas.draw_idle()
        # update boolean image with selected pixels
        vec_bool = self.im_bool.flatten()
        vec_bool[lin[self.ind]] = 1
        self.im_bool = vec_bool.reshape(self.im_bool.shape)

    def disconnect(self):
        self.lasso.disconnect_events()

def label_images(metadata,settings):
    """
    Interactively label satellite images and save the training data.

    KV WRL 2018

    Arguments:
    -----------
        metadata: dict
            contains all the information about the satellite images that were downloaded
        settings: dict
            contains the following fields:
        cloud_thresh: float
            value between 0 and 1 indicating the maximum cloud fraction in the image that is accepted
        sitename: string
            name of the site (also name of the folder where the images are stored)
        cloud_mask_issue: boolean
            True if there is an issue with the cloud mask and sand pixels are being masked on the images
        labels: dict
            the label name (key) and label number (value) for each class
        flood_fill: boolean
            True to use the flood_fill functionality when labelling sand pixels
        tolerance: float
            tolerance used for flood fill when labelling the sand pixels
        filepath_train: str
            directory in which to save the labelled data

    Returns:
    -----------

    """
    filepath_train = settings['filepath_train']
    # initialize figure
    fig,ax = plt.subplots(1,1,figsize=[17,10], tight_layout=True,sharex=True,
                          sharey=True)
    mng = plt.get_current_fig_manager()                                         
    mng.window.showMaximized()

    # loop through satellites
    for satname in metadata.keys():
        filepath = SDS_tools.get_filepath(settings['inputs'],satname)
        filenames = metadata[satname]['filenames']
        # loop through images
        for i in range(len(filenames)):
            # image filename
            fn = SDS_tools.get_filenames(filenames[i],filepath, satname)
            # read and preprocess image
            im_ms, georef, cloud_mask, im_extra, im_QA, im_nodata = SDS_preprocess.preprocess_single(fn, satname, settings['cloud_mask_issue'])
            # calculate cloud cover
            cloud_cover = np.divide(sum(sum(cloud_mask.astype(int))),
                                    (cloud_mask.shape[0]*cloud_mask.shape[1]))
            # skip image if cloud cover is above threshold
            if cloud_cover > settings['cloud_thresh'] or cloud_cover == 1:
                continue
            # get individual RGB image
            im_RGB = SDS_preprocess.rescale_image_intensity(im_ms[:,:,[2,1,0]], cloud_mask, 99.9)
            im_NDVI = SDS_tools.nd_index(im_ms[:,:,3], im_ms[:,:,2], cloud_mask)
            im_NDWI = SDS_tools.nd_index(im_ms[:,:,3], im_ms[:,:,1], cloud_mask)
            # initialise labels
            im_viz = im_RGB.copy()
            im_labels = np.zeros([im_RGB.shape[0],im_RGB.shape[1]])
            # show RGB image
            ax.axis('off')  
            ax.imshow(im_RGB)
            implot = ax.imshow(im_viz, alpha=0.6)            
            
            ##############################################################
            # select image to label
            ##############################################################           
            # set a key event to accept/reject the detections (see https://stackoverflow.com/a/15033071)
            # this variable needs to be immuatable so we can access it after the keypress event
            key_event = {}
            def press(event):
                # store what key was pressed in the dictionary
                key_event['pressed'] = event.key
            # let the user press a key, right arrow to keep the image, left arrow to skip it
            # to break the loop the user can press 'escape'
            while True:
                btn_keep = ax.text(1.1, 0.9, 'keep ⇨', size=12, ha="right", va="top",
                                    transform=ax.transAxes,
                                    bbox=dict(boxstyle="square", ec='k',fc='w'))
                btn_skip = ax.text(-0.1, 0.9, '⇦ skip', size=12, ha="left", va="top",
                                    transform=ax.transAxes,
                                    bbox=dict(boxstyle="square", ec='k',fc='w'))
                btn_esc = ax.text(0.5, 0, '<esc> to quit', size=12, ha="center", va="top",
                                    transform=ax.transAxes,
                                    bbox=dict(boxstyle="square", ec='k',fc='w'))
                fig.canvas.draw_idle()                         
                fig.canvas.mpl_connect('key_press_event', press)
                plt.waitforbuttonpress()
                # after button is pressed, remove the buttons
                btn_skip.remove()
                btn_keep.remove()
                btn_esc.remove()
                
                # keep/skip image according to the pressed key, 'escape' to break the loop
                if key_event.get('pressed') == 'right':
                    skip_image = False
                    break
                elif key_event.get('pressed') == 'left':
                    skip_image = True
                    break
                elif key_event.get('pressed') == 'escape':
                    plt.close()
                    raise StopIteration('User cancelled labelling images')
                else:
                    plt.waitforbuttonpress()
                    
            # if user decided to skip show the next image
            if skip_image:
                ax.clear()
                continue
            # otherwise label this image
            else:
                ##############################################################
                # digitize sandy pixels
                ##############################################################
                # let user know if flood_fill is activated or not
                if settings['flood_fill']:
                    ax.set_title('Left-click on SAND pixels (flood fill activated)\nwhen finished click on <Enter>')
                else:
                    ax.set_title('Left-click on SAND pixels (flood fill deactivated)\nwhen finished click on <Enter>')
                # create erase button, if you click there it delets the last selection
                btn_erase = ax.text(0.9*im_ms.shape[0], 0, 'Erase', size=20, ha="left", va="top",
                                    bbox=dict(boxstyle="square", ec='k',fc='w'))                
                fig.canvas.draw_idle()
                color_sand = settings['colors']['sand']
                pt_sand= []
                while 1:
                    seed = ginput(n=1, timeout=0, show_clicks=True)
                    # if empty break the loop and go to next label
                    if len(seed) == 0:
                        break
                    else:
                        # round to pixel location
                        seed = np.round(seed[0]).astype(int)     
                    # if user clicks on erase
                    if seed[0] > 0.9*im_ms.shape[0] and seed[1] < 0.05*im_ms.shape[1]:
                        # if flood_fill activated, reset the labels (clean restart) 
                        if settings['flood_fill']:
                            im_labels = np.zeros([im_ms.shape[0],im_ms.shape[1]])
                            im_viz = im_RGB.copy()
                            implot.set_data(im_viz)
                            fig.canvas.draw_idle()
                        # otherwise just remove the last point
                        else:
                            if len(pt_sand) > 0:
                                im_labels[pt_sand[1],pt_sand[0]] = 0
                                for k in range(im_viz.shape[2]):
                                    im_viz[pt_sand[1],pt_sand[0],k] = im_RGB[pt_sand[1],pt_sand[0],k]
                                implot.set_data(im_viz)
                                fig.canvas.draw_idle() 
                    # if user clicks on other point
                    else:
                        # if flood_fill activated 
                        if settings['flood_fill']:
                            # flood fill the NDVI and the NDWI
                            fill_NDVI = flood(im_NDVI, (seed[1],seed[0]), tolerance=settings['tolerance'])
                            fill_NDWI = flood(im_NDWI, (seed[1],seed[0]), tolerance=settings['tolerance'])
                            # compute the intersection of the two masks
                            fill_sand = np.logical_and(fill_NDVI, fill_NDWI)
                            im_labels[fill_sand] = settings['labels']['sand'] 
                        # otherwise digitize the individual pixel
                        else:
                            pt_sand = seed
                            im_labels[pt_sand[1],pt_sand[0]] = settings['labels']['sand']
                            
                        # show the labelled pixels
                        for k in range(im_viz.shape[2]):                              
                            im_viz[im_labels==settings['labels']['sand'],k] = color_sand[k]
                        implot.set_data(im_viz)
                        fig.canvas.draw_idle()                         
                        
                ##############################################################
                # digitize white-water pixels
                ##############################################################
                color_ww = settings['colors']['white-water']
                ax.set_title('Left-click on individual WHITE-WATER pixels (no flood fill)\nwhen finished click on <Enter>')
                fig.canvas.draw_idle()                         
                pt_ww= []
                while 1:
                    seed = ginput(n=1, timeout=0, show_clicks=True)
                    # if empty break the loop and go to next label
                    if len(seed) == 0:
                        break
                    else:
                        # round to pixel location
                        seed = np.round(seed[0]).astype(int)     
                    # if user clicks on erase remove the last point
                    if seed[0] > 0.9*im_ms.shape[0] and seed[1] < 0.05*im_ms.shape[1]:
                            if len(pt_ww) > 0:
                                im_labels[pt_ww[1],pt_ww[0]] = 0
                                for k in range(im_viz.shape[2]):
                                    im_viz[pt_ww[1],pt_ww[0],k] = im_RGB[pt_ww[1],pt_ww[0],k]
                                implot.set_data(im_viz)
                                fig.canvas.draw_idle()  
                    else:
                        pt_ww = seed
                        im_labels[pt_ww[1],pt_ww[0]] = settings['labels']['white-water']  
                        for k in range(im_viz.shape[2]):                              
                            im_viz[pt_ww[1],pt_ww[0],k] = color_ww[k]
                        implot.set_data(im_viz)
                        fig.canvas.draw_idle()
                        
                # can't erase any more
                btn_erase.remove()

                ##############################################################
                # digitize water pixels (with lassos)
                ##############################################################
                color_water = settings['colors']['water']
                ax.set_title('Click and hold to select WATER pixels with lassos\nwhen finished click on <Enter>')
                fig.canvas.draw_idle() 
                selector_water = SelectFromImage(ax, implot, color_water)
                key_event = {}
                while True:
                    fig.canvas.draw_idle()                         
                    fig.canvas.mpl_connect('key_press_event', press)
                    plt.waitforbuttonpress()
                    if key_event.get('pressed') == 'enter':
                        selector_water.disconnect()
                        break
                # update im_viz and im_labels
                im_viz = selector_water.array
                selector_water.im_bool = selector_water.im_bool.astype(bool)
                im_labels[selector_water.im_bool] = settings['labels']['water']
                
                ##############################################################
                # digitize land pixels (with lassos)
                ##############################################################
                color_land = settings['colors']['other land features']
                ax.set_title('Click and hold to select OTHER LAND pixels with lassos\nwhen finished click on <Enter>')
                fig.canvas.draw_idle() 
                selector_land = SelectFromImage(ax, implot, color_land)
                key_event = {}
                while True:
                    fig.canvas.draw_idle()                         
                    fig.canvas.mpl_connect('key_press_event', press)
                    plt.waitforbuttonpress()
                    if key_event.get('pressed') == 'enter':
                        selector_land.disconnect()
                        break
                # update im_viz and im_labels
                im_viz = selector_land.array
                selector_land.im_bool = selector_land.im_bool.astype(bool)
                im_labels[selector_land.im_bool] = settings['labels']['other land features']  
                
                # save labelled image
                filename = filenames[i][:filenames[i].find('.')][:-4] 
                ax.set_title(filename)
                fig.canvas.draw_idle()                         
                fp = os.path.join(filepath_train,settings['inputs']['sitename'])
                if not os.path.exists(fp):
                    os.makedirs(fp)
                fig.savefig(os.path.join(fp,filename+'.jpg'), dpi=200)
                ax.clear()
                # save labels and features
                features = dict([])
                for key in settings['labels'].keys():
                    im_bool = im_labels == settings['labels'][key]
                    features[key] = SDS_shoreline.calculate_features(im_ms, cloud_mask, im_bool)
                training_data = {'labels':im_labels, 'features':features, 'label_ids':settings['labels']}
                with open(os.path.join(fp, filename + '.pkl'), 'wb') as f:
                    pickle.dump(training_data,f)
                    
    # close figure when finished
    plt.close(fig)

def load_labels(train_sites, settings):
    
    filepath_train = settings['filepath_train']
    # initialize the features dict
    features = dict([])
    n_features = 20
    first_row = np.nan*np.ones((1,n_features))
    for key in settings['labels'].keys():
        features[key] = first_row
    # loop through each site 
    for site in train_sites:
        sitename = site[:site.find('.')] 
        filepath = os.path.join(filepath_train,sitename)
        if os.path.exists(filepath):
            list_files = os.listdir(filepath)
        else:
            continue
        # make a new list with only the .pkl files (no .jpg)
        list_files_pkl = []
        for file in list_files:
            if '.pkl' in file:
                list_files_pkl.append(file)
        # load and append the training data to the features dict
        for file in list_files_pkl:
            # read file
            with open(os.path.join(filepath, file), 'rb') as f:
                labelled_data = pickle.load(f) 
            for key in labelled_data['features'].keys():
                if len(labelled_data['features'][key])>0: # check that is not empty
                    # append rows
                    features[key] = np.append(features[key],
                                labelled_data['features'][key], axis=0)  
    # remove the first row (initialized with nans)
    print('Number of pixels per class in training data:')
    for key in features.keys(): 
        features[key] = features[key][1:,:]
        print('%s : %d pixels'%(key,len(features[key])))
    
    return features
        

def check_classifier(classifier, metadata, settings):
    """
    Interactively visualise the new classifier.

    KV WRL 2018

    Arguments:
    -----------
        classifier: joblib object
            Multilayer Perceptron to be used for image classification
        metadata: dict
            contains all the information about the satellite images that were downloaded
        settings: dict
            contains the following fields:
        cloud_thresh: float
            value between 0 and 1 indicating the maximum cloud fraction in the image that is accepted
        sitename: string
            name of the site (also name of the folder where the images are stored)
        cloud_mask_issue: boolean
            True if there is an issue with the cloud mask and sand pixels are being masked on the images
        labels: dict
            the label name (key) and label number (value) for each class
        tolerance: float
            tolerance used for flood fill when labelling the sand pixels
        filepath_train: str
            directory in which to save the labelled data

    Returns:
    -----------

    """  
    # initialize figure
    fig,ax = plt.subplots(1,2,figsize=[17,10],sharex=True, sharey=True,constrained_layout=True)
    mng = plt.get_current_fig_manager()                                         
    mng.window.showMaximized()  

    # create colormap for labels
    cmap = cm.get_cmap('tab20c')
    colorpalette = cmap(np.arange(0,13,1))
    colours = np.zeros((3,4))
    colours[0,:] = colorpalette[5]
    colours[1,:] = np.array([204/255,1,1,1])
    colours[2,:] = np.array([0,91/255,1,1])
    # loop through satellites
    for satname in metadata.keys():
        filepath = SDS_tools.get_filepath(settings['inputs'],satname)
        filenames = metadata[satname]['filenames']
        # loop through images
        for i in range(len(filenames)):   
            # image filename
            fn = SDS_tools.get_filenames(filenames[i],filepath, satname)
            # read and preprocess image
            im_ms, georef, cloud_mask, im_extra, im_QA, im_nodata = SDS_preprocess.preprocess_single(fn, satname, settings['cloud_mask_issue'])
            # calculate cloud cover
            cloud_cover = np.divide(sum(sum(cloud_mask.astype(int))),
                                    (cloud_mask.shape[0]*cloud_mask.shape[1]))
            # skip image if cloud cover is above threshold
            if cloud_cover > settings['cloud_thresh'] or cloud_cover == 1:
                continue
            im_RGB = SDS_preprocess.rescale_image_intensity(im_ms[:,:,[2,1,0]], cloud_mask, 99.9)
            # classify image
            features = SDS_shoreline.calculate_features(im_ms,
                                    cloud_mask, np.ones(cloud_mask.shape).astype(bool))
            features[np.isnan(features)] = 1e-9
            # remove NaNs and clouds
            vec_cloud = cloud_mask.reshape(cloud_mask.shape[0]*cloud_mask.shape[1])
            vec_nan = np.any(np.isnan(features), axis=1)
            vec_mask = np.logical_or(vec_cloud, vec_nan)
            features = features[~vec_mask, :]
            # predict with NN classifier
            labels = classifier.predict(features)
            # recompose image
            vec_classif = np.nan*np.ones((cloud_mask.shape[0]*cloud_mask.shape[1])) 
            vec_classif[~vec_mask] = labels
            im_classif = vec_classif.reshape((cloud_mask.shape[0], cloud_mask.shape[1]))
            # labels
            im_sand = im_classif == 1
            # remove small patches of sand
    #        im_sand = morphology.remove_small_objects(im_sand, min_size=25, connectivity=2)
            im_swash = im_classif == 2
            im_water = im_classif == 3
#            im_land = im_classif == 0
            im_labels = np.stack((im_sand,im_swash,im_water), axis=-1)   
            # create classified image
            im_class = np.copy(im_RGB)
            for k in range(0,im_labels.shape[2]):
                im_class[im_labels[:,:,k],0] = colours[k,0]
                im_class[im_labels[:,:,k],1] = colours[k,1]
                im_class[im_labels[:,:,k],2] = colours[k,2]        
            # show images
            ax[0].imshow(im_RGB)
            ax[1].imshow(im_RGB)
            ax[1].imshow(im_class, alpha=0.5)
            ax[0].axis('off')
            ax[1].axis('off')
            filename = filenames[i][:filenames[i].find('.')][:-4] 
            ax[0].set_title(filename)

            # set a key event to accept/reject the detections (see https://stackoverflow.com/a/15033071)
            # this variable needs to be immuatable so we can access it after the keypress event
            key_event = {}
            def press(event):
                # store what key was pressed in the dictionary
                key_event['pressed'] = event.key
            # let the user press a key, right arrow to keep the image, left arrow to skip it
            # to break the loop the user can press 'escape'
            while True:
                btn_keep = ax[0].text(1, 0.9, 'next image ⇨', size=14, ha="right", va="top",
                                    transform=ax[0].transAxes,
                                    bbox=dict(boxstyle="square", ec='k',fc='w'))
                btn_skip = ax[0].text(0, 0.9, '⇦ next site', size=14, ha="left", va="top",
                                    transform=ax[0].transAxes,
                                    bbox=dict(boxstyle="square", ec='k',fc='w'))
                btn_esc = ax[0].text(0.5, 0, '<esc> to quit', size=14, ha="center", va="top",
                                    transform=ax[0].transAxes,
                                    bbox=dict(boxstyle="square", ec='k',fc='w'))
                plt.draw()
                fig.canvas.mpl_connect('key_press_event', press)
                plt.waitforbuttonpress()
                # after button is pressed, remove the buttons
                btn_skip.remove()
                btn_keep.remove()
                btn_esc.remove()
                # keep/skip image according to the pressed key, 'escape' to break the loop
                if key_event.get('pressed') == 'right':
                    skip_image = False
                    break
                elif key_event.get('pressed') == 'left':
                    skip_image = True
                    break
                elif key_event.get('pressed') == 'escape':
                    plt.close()
                    raise StopIteration('User cancelled visualising images')
                else:
                    plt.waitforbuttonpress()
            
            # save figure
            if settings['save_figure']:
                fp = os.path.join(settings['filepath_train'],
                                  settings['inputs']['sitename']+'_check')
                if not os.path.exists(fp):
                    os.makedirs(fp)
                fig.savefig(os.path.join(fp,filename+'.jpg'), dpi=200)
            if skip_image:
                for cax in fig.axes:
                   cax.clear()
                break
            else:
                for cax in fig.axes:
                   cax.clear()
                continue
            
    # close the figure at the end
    plt.close()
    
def format_training_data(features, classes, labels):
    # initialize X and y
    X = np.nan*np.ones((1,features[classes[0]].shape[1]))
    y = np.nan*np.ones((1,1))
    # append row of features to X and corresponding label to y 
    for i,key in enumerate(classes):
        y = np.append(y, labels[i]*np.ones((features[key].shape[0],1)), axis=0)
        X = np.append(X, features[key], axis=0)
    # remove first row
    X = X[1:,:]; y = y[1:]
    # replace nans with something close to 0
    # training algotihms cannot handle nans
    X[np.isnan(X)] = 1e-9 
    
    return X, y

def plot_confusion_matrix(y_true,y_pred,classes,normalize=False,cmap=plt.cm.Blues):
    """
    Function copied from the scikit-learn examples (https://scikit-learn.org/stable/)
    This function prints and plots the confusion matrix.
    Normalization can be applied by setting `normalize=True`.
    """
    # compute confusion matrix
    cm = confusion_matrix(y_true, y_pred)
    if normalize:
        cm = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]
        print("Normalized confusion matrix")
    else:
        print('Confusion matrix, without normalization')
        
    # plot confusion matrix
    fig, ax = plt.subplots(figsize=(6,6), tight_layout=True)
    im = ax.imshow(cm, interpolation='nearest', cmap=cmap)
#    ax.figure.colorbar(im, ax=ax)
    ax.set(xticks=np.arange(cm.shape[1]),
           yticks=np.arange(cm.shape[0]), ylim=[3.5,-0.5],
           xticklabels=classes, yticklabels=classes,
           ylabel='True label',
           xlabel='Predicted label')

    # rotate the tick labels and set their alignment.
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right",
             rotation_mode="anchor")

    # loop over data dimensions and create text annotations.
    fmt = '.2f' if normalize else 'd'
    thresh = cm.max() / 2.
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, format(cm[i, j], fmt),
                    ha="center", va="center",
                    color="white" if cm[i, j] > thresh else "black",
                    fontsize=12)
    fig.tight_layout()
    return ax